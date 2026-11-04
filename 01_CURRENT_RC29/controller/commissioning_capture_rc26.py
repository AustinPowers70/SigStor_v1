#!/usr/bin/env python3
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
