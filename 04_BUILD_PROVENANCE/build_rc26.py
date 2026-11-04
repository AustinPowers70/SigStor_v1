from pathlib import Path
import shutil,hashlib,zipfile,subprocess,sys,textwrap
base=Path('/mnt/data'); work=base/'work_rc26'; root=work/'SigenStor_Phase3B_RC26'
if work.exists():shutil.rmtree(work)
shutil.copytree(base/'work_rc25'/'SigenStor_Phase3B_RC25',root,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
(root/'controller'/'commissioning_capture_rc26.py').write_text('''#!/usr/bin/env python3
"""RC26 real read-only power trace and evidence alignment for attended pilot.

This program NEVER issues Modbus writes, manages control authority, launches a
controller, or asserts battery-attributable grid-side energy delivery. It uses
our already commissioned FC04 telemetry decoder. Do not confuse concurrent
capture with authority to run a live commissioning pulse.
"""
import argparse,datetime as dt,json,math,os,pathlib,sys,time
from power_acquisition_rc9 import sample_once,append

SCHEMA='SIGEN_PHASE3B_RC26_READONLY_POWER_TRACE'
class CaptureHold(RuntimeError): pass

def capture(seconds=75, interval=2, read=sample_once, now=None,clock=time.monotonic,sleep=time.sleep,write=append,path=None):
    if type(seconds) not in (int,float) or not 30<=seconds<=180 or type(interval) not in (int,float) or not 1<=interval<=2:
        raise CaptureHold('bounded read-only capture: 30-180 s, 1-2 s interval')
    if path is None:raise CaptureHold('output path required')
    now=now or (lambda:dt.datetime.now(dt.timezone.utc))
    start=clock();end=start+seconds;last=None;rows=0;errors=0
    while clock()<end:
        stamp=now();tick=clock();ok=False;error='';values={}
        try:
            values=read()
            if not isinstance(values,dict):raise ValueError('sample is not a dict')
            for key in ('soc_pct','battery_kw','grid_kw','pv_kw','home_kw'):
                v=values[key]
                if isinstance(v,bool) or type(v) not in (int,float) or not math.isfinite(v):raise ValueError('invalid '+key)
            if not 0<=values['soc_pct']<=100:raise ValueError('SOC out of range')
            ok=True
        except (OSError,RuntimeError,ValueError,KeyError,TypeError) as exc:
            error=type(exc).__name__+': '+str(exc);errors+=1
        if stamp.tzinfo is None:raise CaptureHold('naive UTC clock')
        if last is not None and tick<last:raise CaptureHold('monotonic clock regressed')
        last=tick
        record={'schema':SCHEMA,'utc':stamp.astimezone(dt.timezone.utc).isoformat(),
                'elapsed_s':round(tick-start,3),'valid':ok,'error':error,
                'grid_side_battery_delivery_verified':False,'modbus_writes':0}
        for key in ('soc_pct','battery_kw','grid_kw','pv_kw','home_kw'):
            record[key]=float(values[key]) if ok else None
        write(path,record);rows+=1
        left=end-clock()
        if left>0:sleep(min(left,max(0,interval-(clock()-tick))))
    return {'schema':'SIGEN_PHASE3B_RC26_CAPTURE','samples':rows,'invalid_samples':errors,
            'status':'RECORDED' if errors==0 and rows>=2 else 'INCOMPLETE',
            'modbus_writes':0,'physical_delivery_verified':False}

def _load(path,limit=1500):
    p=pathlib.Path(path)
    if p.stat().st_size>1_000_000:raise CaptureHold('file too large')
    with p.open(encoding='utf8') as f:
        items=[json.loads(line) for line in f if line.strip()]
    if len(items)>limit:raise CaptureHold('too many samples')
    return items

def assess(rows):
    if not isinstance(rows,list) or len(rows)<2:raise CaptureHold('insufficient samples')
    valid=[];previous=None;bad=0
    for r in rows:
        if not isinstance(r,dict) or r.get('schema')!=SCHEMA or r.get('modbus_writes')!=0:
            raise CaptureHold('trace schema or write-count mismatch')
        stamp=dt.datetime.fromisoformat(r['utc'].replace('Z','+00:00'))
        if stamp.tzinfo is None or (previous is not None and stamp<=previous):raise CaptureHold('nonmonotonic UTC evidence')
        previous=stamp
        if r.get('valid') is True:
            vals=[]
            for key in ('soc_pct','battery_kw','grid_kw','home_kw'):
                value=r.get(key)
                if type(value) not in (int,float) or not math.isfinite(value):raise CaptureHold('invalid value '+key)
                vals.append(value)
            if not 0<=vals[0]<=100:raise CaptureHold('invalid SOC')
            valid.append((stamp,vals))
        else:bad+=1
    coverage=round(len(valid)/len(rows),4)
    gaps=[(valid[i][0]-valid[i-1][0]).total_seconds() for i in range(1,len(valid))]
    # Trapezoidal battery-port energy only: -battery_kw = charging, + = discharging.
    # Exclude gaps >6s so missing data never becomes fictitious integrated energy.
    batt_wh=grid_wh=integrated_s=0.
    for i in range(1,len(valid)):
        dt_s=gaps[i-1]
        if not 0<dt_s<=6:continue
        batt_wh+=dt_s*(valid[i-1][1][1]+valid[i][1][1])/7.2
        grid_wh+=dt_s*(valid[i-1][1][2]+valid[i][1][2])/7.2
        integrated_s+=dt_s
    return {'schema':'SIGEN_PHASE3B_RC26_EVIDENCE_REVIEW',
            'status':'REVIEW_TRACE' if coverage>=0.8 and max(gaps or [999])<=6 else 'HOLD_INCOMPLETE_TRACE',
            'samples':len(rows),'valid_samples':len(valid),'coverage':coverage,
            'largest_valid_gap_s':round(max(gaps),3) if gaps else None,
            'integrated_seconds':round(integrated_s,2),
            'battery_port_wh_signed_positive_charging':round(batt_wh,3),
            'aggregate_grid_wh_signed_positive_import':round(grid_wh,3),
            'battery_grid_side_delivery_verified':False,
            'notes':'Battery-port and aggregate-grid estimates only. Operator pilot event correlation and physical energy attribution require commissioning review.',
            'modbus_writes':0,'autonomous_dispatch':False}

def main(argv=None):
    ap=argparse.ArgumentParser(description='Read-only commissioning evidence recorder, no actuator')
    group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--capture',action='store_true');group.add_argument('--assess',action='store_true')
    ap.add_argument('--file',type=pathlib.Path,required=True)
    ap.add_argument('--seconds',type=int,default=75)
    args=ap.parse_args(argv)
    try:
        if args.capture:
            if args.file.exists():raise CaptureHold('refusing overwrite: choose new file')
            result=capture(seconds=args.seconds,path=args.file)
        else:result=assess(_load(args.file))
        print(json.dumps(result,sort_keys=True,allow_nan=False));return 0 if result['status'] in ('RECORDED','REVIEW_TRACE') else 2
    except (OSError,ValueError,TypeError,KeyError) as exc:
        print('RC26_CAPTURE_HOLD',type(exc).__name__,str(exc),'MODBUS_WRITES=0');return 2
if __name__=='__main__':sys.exit(main())
''')
# Correct factor for conversion kW*s -> Wh: /3.6, trapezoid factor 1/2 => /7.2 is correct.
(root/'tests'/'test_rc26.py').write_text('''import unittest,sys,pathlib,tempfile,datetime as dt
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'controller'))
from commissioning_capture_rc26 import capture,assess,CaptureHold,SCHEMA
class Tests(unittest.TestCase):
 def test_capture_integrates_real_signed_port_units(self):
  state={'t':0};origin=dt.datetime(2026,11,4,tzinfo=dt.timezone.utc);rows=[]
  def read():return {'soc_pct':60.,'battery_kw':7.2,'grid_kw':3.6,'pv_kw':0.,'home_kw':0.}
  capture(seconds=30,interval=2,read=read,now=lambda:origin+dt.timedelta(seconds=state['t']),
      clock=lambda:state['t'],sleep=lambda n:state.__setitem__('t',state['t']+n),write=lambda p,r:rows.append(r),path='/unused')
  out=assess(rows)
  self.assertEqual(out['status'],'REVIEW_TRACE');self.assertEqual(out['valid_samples'],15)
  self.assertAlmostEqual(out['battery_port_wh_signed_positive_charging'],56.,places=3)
  self.assertFalse(out['battery_grid_side_delivery_verified'])
 def test_stale_trace_hold(self):
  origin=dt.datetime(2026,11,4,tzinfo=dt.timezone.utc)
  rows=[{'schema':SCHEMA,'utc':(origin+dt.timedelta(seconds=t)).isoformat(),'valid':True,
         'soc_pct':60.,'battery_kw':0.,'grid_kw':0.,'home_kw':0.,'modbus_writes':0} for t in (0,12)]
  self.assertEqual(assess(rows)['status'],'HOLD_INCOMPLETE_TRACE')
 def test_invalid_power_fails(self):
  origin=dt.datetime(2026,11,4,tzinfo=dt.timezone.utc)
  rows=[{'schema':SCHEMA,'utc':(origin+dt.timedelta(seconds=t)).isoformat(),'valid':True,
         'soc_pct':60.,'battery_kw':float('nan'),'grid_kw':0.,'home_kw':0.,'modbus_writes':0} for t in (0,2)]
  with self.assertRaises(CaptureHold):assess(rows)
 def test_capture_no_modbus_writes(self):
  state={'t':0};rows=[];origin=dt.datetime(2026,11,4,tzinfo=dt.timezone.utc)
  r=capture(seconds=30,interval=2,read=lambda:{'soc_pct':60.,'battery_kw':0.,'grid_kw':0.,'pv_kw':0.,'home_kw':0.},
      now=lambda:origin+dt.timedelta(seconds=state['t']),clock=lambda:state['t'],
      sleep=lambda n:state.__setitem__('t',state['t']+n),write=lambda p,r:rows.append(r),path='/unused')
  self.assertEqual(r['modbus_writes'],0)
 def test_wrong_schema(self):
  with self.assertRaises(CaptureHold):assess([{'schema':'fake'},{'schema':'fake'}])
''')
(root/'COMMISSIONING_RC26.md').write_text('''# RC26 — Physical commissioning evidence capture (READ ONLY)

## Why this package

RC25 (314/314 on Thor) already validates simulation and audit ordering. The missing evidence is a time-aligned physical power trace when an experienced operator elects to use the **previously commissioned** operator-driven pilot. RC26 installs an actual 1–2 s FC04 passive capture and quantitative assessor, not another simulated actuation release.

The package **does not actuate the inverter** and cannot run a pilot. It does not add any timer or service. Source RC13 remains unchanged. No 40034 writes. Do not claim physical battery-attributable grid-side energy from a battery-port and an aggregate-grid trace alone.

## Independent read-only plant check

`python3 -B /opt/sigenstor/scripts/phase3b-supervised-rc26/controller/commissioning_preflight_rc18.py --check`

## Read-only capture, with operator supervising MySigen

`python3 -B /opt/sigenstor/scripts/phase3b-supervised-rc26/controller/commissioning_capture_rc26.py --capture --seconds 75 --file /opt/sigenstor/data/rtm/rc26-pilot-20261104T1800Z.jsonl`

A separate, operator-approved, previously commissioned 30-second pulse would occur only after an explicit live-plant commissioning decision. The record command never initiates it. Capture starts before the pulse and continues past handback. Choose a *new unique* filename per session; RC26 will not overwrite evidence. Since 75 seconds of capture is timed, launch/coordinate separate operator control as appropriate. Independent Thor-loss recovery is not provided.

## Assessment

`python3 -B /opt/sigenstor/scripts/phase3b-supervised-rc26/controller/commissioning_capture_rc26.py --assess --file /opt/sigenstor/data/rtm/rc26-pilot-20261104T1800Z.jsonl`

Signed battery port: positive charging, negative discharging in the original FC04 decoder; grid positive importing, negative exporting. The battery-port Wh and aggregate-grid Wh are *separate* integrations, not one proven meter-side energy flow. Samples separated >6 seconds are excluded from integration; a coverage/gap hold prevents unwarranted acceptance. The actual physical pilot times and pre/post handback readbacks must also be correlated before declaring success.

## Commissioning boundary

A full-duration or unattended session is NOT authorised. A shorter manual-attended real pulse has nonzero risk of continued Remote EMS actuation if Thor or its network fails at the wrong moment. Live operations require a new explicit operator decision; staging this bundle does not grant that consent.
''')
(root/'install.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
sha256sum -c SHA256SUMS
# Focus only on the newly introduced physical evidence recorder. RC25's 314 tests passed on Thor.
python3 -B -m unittest discover -s tests -p 'test_rc26.py' -q
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc26
if [[ -e "$TARGET" ]]; then echo 'RC26 already present; refusing overwrite'; exit 2; fi
mkdir -p "$TARGET"
cp -a controller accepted tests *.md SHA256SUMS "$TARGET"/
echo 'RC26 staged: REAL READ-ONLY POWER CAPTURE; NO SERVICES OR MODBUS WRITES.'
''')
(root/'rollback.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc26
if [[ -d "$TARGET" ]]; then echo 'RC26 is standalone staging, no active service to roll back. RC25 retained.'; fi
''')
(root/'RELEASE_NOTES_RC26.md').write_text('''# RC26 — Real power evidence capture
RC25 accepted on Thor with 314/314 offline tests. RC26 adds a real FC04 75-second sample collector and an evidence assessor, uses the previous validated decoding library, and does not change or launch any live Modbus actuation code. Five targeted tests replace a pointless repeat of the 314-test suite. Controlled physical pilot approval remains a separate operator action. No independent Thor-loss recovery claimed.
''')
# Clean outdated binary and hash
for p in root.rglob('__pycache__'):shutil.rmtree(p)
for p in root.rglob('*.pyc'):p.unlink()
sha=root/'SHA256SUMS';sha.unlink(missing_ok=True)
with sha.open('w') as f:
 for p in sorted(root.rglob('*')):
  if p.is_file() and p!=sha:
   f.write(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(root).as_posix()+'\n')
(root/'install.sh').chmod(0o755)
result=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests','-p','test_rc26.py','-v'],cwd=root,capture_output=True,text=True)
print(result.stdout+result.stderr)
if result.returncode:raise SystemExit('Targeted tests failed')
archive=base/'SigenStor_Phase3B_RC26_Physical_Evidence_Capture.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=8) as z:
 for p in sorted(root.rglob('*')):
  if p.is_file():z.write(p,p.relative_to(work))
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
print('ARCHIVE',archive,archive.stat().st_size)
