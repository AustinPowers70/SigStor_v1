from pathlib import Path
import shutil,zipfile,hashlib,subprocess,textwrap
src=Path('/mnt/data/work_rc19/SigenStor_Phase3B_RC18')
out=Path('/mnt/data/work_rc19/SigenStor_Phase3B_RC19')
if out.exists(): shutil.rmtree(out)
shutil.copytree(src,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
ctrl=out/'controller'
(ctrl/'commissioning_handoff_rc19.py').write_text('''#!/usr/bin/env python3
"""Consolidated Phase 3B read-only commissioning handoff.

A read-only current snapshot and optional plant inspection. This is a HOLD/REVIEW
report, not a live actuation authority. Inverter-native/independent loss recovery
has not been demonstrated. No Modbus write-capable interface is imported here.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import rc13_gateway
import integrated_preview
import session_integration_rc5

class HandoffError(RuntimeError): pass

DEFAULT_R5=integrated_preview.DEFAULT_R5

def read_doc(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file(): raise HandoffError('missing/symlink source: '+str(p))
    if p.stat().st_size>8*1024*1024: raise HandoffError('oversized source: '+str(p))
    return json.loads(p.read_text(encoding='utf-8'))

def evaluate(*,now,candidate,settings,authority,r5,plant=None,recovery=None):
    if now.tzinfo is None: raise HandoffError('timezone-aware clock required')
    issues=[]
    try:
        plan=session_integration_rc5.prepare(candidate,settings,authority,r5,now)
        if plan.get('state')!='QUALIFIED_SIMULATION_ONLY':
            issues.append('NO_CURRENT_QUALIFIED_SLOT:'+str(plan.get('reason','UNKNOWN')))
    except (ValueError,KeyError,TypeError,RuntimeError) as exc:
        plan={'state':'HOLD','reason':type(exc).__name__+': '+str(exc)}
        issues.append('SOURCE_OR_CONTRACT_INVALID')
    if plant is None:
        issues.append('CURRENT_PLANT_STATE_NOT_CHECKED')
    else:
        if not isinstance(plant,dict) or plant.get('plant_handback_verified') is not True or not all(plant.get(k) is True for k in ('remote_ems_off','self_consumption','pcs_zero')):
            issues.append('PLANT_HANDBACK_NOT_VERIFIED')
        else:
            try:
                observed=rc13_gateway.timestamp(plant['timestamp_utc'])
                age=(now-observed).total_seconds()
                if age < -10 or age>30:issues.append('PLANT_OBSERVATION_STALE')
            except (KeyError,ValueError,TypeError):issues.append('PLANT_OBSERVATION_TIMESTAMP_INVALID')
    # Independent recovery cannot be proven by a self-attestation from this LXC.
    # Only acceptance of externally verified evidence can change this gate.
    recovery_accepted=False
    issues.append('INDEPENDENT_HOST_NETWORK_LOSS_RECOVERY_NOT_VERIFIED')
    issues.append('LIVE_FULL_SLOT_ACTUATOR_NOT_COMMISSIONED')
    return {'schema':'SIGEN_PHASE3B_RC19_COMMISSIONING_HANDOFF',
        'timestamp_utc':now.astimezone(dt.timezone.utc).isoformat(),
        'source_state':plan.get('state'),'source_reason':plan.get('reason'),
        'qualified_action':plan.get('action') if plan.get('state')=='QUALIFIED_SIMULATION_ONLY' else None,
        'source_fingerprint':plan.get('source_fingerprint') if plan.get('state')=='QUALIFIED_SIMULATION_ONLY' else None,
        'plant_handback_checked':plant is not None,
        'independent_recovery_accepted':recovery_accepted,
        'issues':issues,'status':'HOLD_FOR_SUPERVISED_COMMISSIONING',
        'live_execution_enabled':False,'autonomous_dispatch':False,
        'grid_side_battery_delivery_verified':False,'modbus_writes':0}

def main(argv=None):
    p=argparse.ArgumentParser(description='RC19 non-actuating commissioning handoff')
    p.add_argument('--check-plant',action='store_true',help='perform real FC03/FC04 reads only')
    p.add_argument('--execute-slot',action='store_true',help='not implemented: will be refused')
    p.add_argument('--out',type=Path,help='optional report destination; refuses symlinks')
    args=p.parse_args(argv)
    if args.execute_slot:
        print('RC19_BLOCKED: NO LIVE EXECUTION ENTRY POINT; MODBUS_WRITES=0');return 2
    try:
        now=dt.datetime.now(dt.timezone.utc)
        paths=(rc13_gateway.DOC,rc13_gateway.SET,rc13_gateway.AUTH,DEFAULT_R5)
        docs=[read_doc(path) for path in paths]
        plant=None
        if args.check_plant:
            from commissioning_preflight_rc18 import inspect
            plant=inspect()
        report=evaluate(now=now,candidate=docs[0],settings=docs[1],authority=docs[2],r5=docs[3],plant=plant)
        output=json.dumps(report,sort_keys=True,indent=2,allow_nan=False)
        if args.out:
            if args.out.is_symlink() or not args.out.parent.is_dir():raise HandoffError('unsafe output path')
            import os, tempfile
            fd,temp=tempfile.mkstemp(dir=args.out.parent,prefix='.rc19-',suffix='.tmp')
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as f:
                    f.write(output+'\\n');f.flush();os.fsync(f.fileno())
                os.replace(temp,args.out)
            finally:
                if os.path.exists(temp):os.unlink(temp)
        print(output)
        return 0 # HOLD is an expected readiness result; never an execution success
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
        print('RC19_FAIL_CLOSED',type(exc).__name__,str(exc),'MODBUS_WRITES=0');return 2
if __name__=='__main__':raise SystemExit(main())
''')
(out/'tests'/'test_rc19.py').write_text('''import unittest,sys,datetime as dt,importlib.util
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
import commissioning_handoff_rc19 as h

NOW=dt.datetime(2026,11,4,18,0,tzinfo=dt.timezone.utc)
class HandoffTests(unittest.TestCase):
    def report(self,plant=None):
        # Invalid documents must fail closed without propagating dispatch.
        return h.evaluate(now=NOW,candidate={},settings={},authority={},r5={},plant=plant)
    def test_invalid_source_hold(self):
        r=self.report();self.assertEqual(r['status'],'HOLD_FOR_SUPERVISED_COMMISSIONING');self.assertIn('SOURCE_OR_CONTRACT_INVALID',r['issues'])
    def test_no_writes(self):self.assertEqual(self.report()['modbus_writes'],0)
    def test_no_auto(self):self.assertFalse(self.report()['autonomous_dispatch'])
    def test_no_live(self):self.assertFalse(self.report()['live_execution_enabled'])
    def test_no_grid_side_claim(self):self.assertFalse(self.report()['grid_side_battery_delivery_verified'])
    def test_missing_plant(self):self.assertIn('CURRENT_PLANT_STATE_NOT_CHECKED',self.report()['issues'])
    def test_unhanded_plant(self):self.assertIn('PLANT_HANDBACK_NOT_VERIFIED',self.report({})['issues'])
    def test_stale_plant(self):
        p=dict(plant_handback_verified=True,remote_ems_off=True,self_consumption=True,pcs_zero=True,timestamp_utc='2026-11-04T17:55:00Z')
        self.assertIn('PLANT_OBSERVATION_STALE',self.report(p)['issues'])
    def test_good_plant_does_not_unlock(self):
        p=dict(plant_handback_verified=True,remote_ems_off=True,self_consumption=True,pcs_zero=True,timestamp_utc='2026-11-04T18:00:00Z')
        r=self.report(p);self.assertTrue(r['plant_handback_checked']);self.assertFalse(r['live_execution_enabled']);self.assertIn('INDEPENDENT_HOST_NETWORK_LOSS_RECOVERY_NOT_VERIFIED',r['issues'])
    def test_execute_blocked(self):self.assertEqual(h.main(['--execute-slot']),2)
    def test_no_write_interface(self):
        s=Path(h.__file__).read_text();self.assertNotIn('write_u32(',s);self.assertNotIn('40034,',s)
    def test_naive_rejected(self):
        with self.assertRaises(h.HandoffError):h.evaluate(now=dt.datetime(2026,11,4),candidate={},settings={},authority={},r5={})
    def test_recovery_is_not_self_attested(self):self.assertFalse(self.report()['independent_recovery_accepted'])
if __name__=='__main__':unittest.main()
''')
(out/'COMMISSIONING_HANDOFF.md').write_text('''# Phase 3B — Supervised commissioning handoff (RC19)

## Baseline
RC18 on Thor accepted: 226/226 offline tests; manual read-only live preflight at 2026-11-01T18:22:17Z confirmed 40029=0, 40031=2, PCS request zero, SOC 60.4%, battery -7.484 kW and aggregate grid +0.006 kW. No physical energy allocation verified. These readings are historical, not current.

## Development frozen
RC13 economics unchanged. All full-slot write entrypoints remain disabled. RC19 produces a current *read-only* assessment; it does not carry a live session token, transport writer, or dispatch flag. The existing 30-second supervised pilots must not be lengthened by direct calls.

## Outstanding gates before FULL-SLOT actuation
1. Obtain independently effective loss-of-host/network/Modbus communications recovery: an inverter-native bounded EMS timeout that has been **verified** in a safe commissioning test, or a genuinely independent supervisory device. An application timer inside the same Thor LXC is not independent recovery.
2. Commission real single-writer authority and exclusive lock ownership; hold the authority panel isolated until positive handback confirmation. Fail closed on handback ambiguity and retain documented operator manual recovery.
3. Bind the 500 W charge/650 W export command contract to session timing, per-sample SOC limits, active qualification and fixed slot expiry. The research-only RC13 source cannot directly authorise live control.
4. Obtain independently grounded grid-side evidence; aggregate grid flow plus battery-port flow alone does not prove delivery allocation. Use the installed two-second readings as supporting evidence; do not use interpolated gaps as actual samples.
5. Execute an operator-attended bounded integrated validation, followed by a qualified full-slot session only when all gates pass, with reviewed rollback and emergency manual handback procedures.

## Operational sequence
- Install this package only from /tmp/copy-paste; do not enable services/timers or start writes.
- Run the RC19 current readiness handoff with --check-plant only when no other session owns the inverter. This reads the plant, it never writes.
- `HOLD_FOR_SUPERVISED_COMMISSIONING` is expected until verified external recovery and the live actuator exist. DO NOT edit a JSON field to bypass the blocker.
- Approval to develop is not approval to dispatch. Each live operation requires an explicitly attended operator action and separate review.

## Rollback
The install is side-by-side with RC18 and changes no services. To remove this staged package, run its rollback.sh. Do not alter live plant state via rollback.
''')
(out/'RELEASE_NOTES.md').write_text('''# Phase 3B RC19 — Consolidated supervised commissioning handoff

Includes the accepted RC18 code unchanged and adds a single read-only, fail-closed readiness report combining current RC13/R5/R6 qualification, optional actual plant handback inspection, and explicit non-negotiable host-loss recovery and live actuator gates. RC13 remains frozen; live writes=0. No autonomous dispatch, service changes, or register 40034 writes.

This package intentionally does not enable live full-slot Modbus execution. It is the engineering handoff that identifies concrete barriers to commissioning rather than another isolated actuator simulation. It can be run with `--check-plant` for read-only real plant inspection at a safe time.
''')
(out/'install.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
sha256sum -c SHA256SUMS
python3 -B -m unittest discover -s tests -p 'test_*.py' -q
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc19
if [[ -e "$TARGET" ]]; then echo 'RC19 already installed; refusing overwrite'; exit 2; fi
mkdir -p "$TARGET"
cp -a controller accepted tests RELEASE_NOTES.md COMMISSIONING_HANDOFF.md SHA256SUMS "$TARGET"/
echo 'RC19 installed READ ONLY; no service or Modbus write changes.'
''')
(out/'rollback.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc19
if [[ -d "$TARGET" && -f "$TARGET/COMMISSIONING_HANDOFF.md" ]]; then
  rm -rf -- "$TARGET"
  echo 'RC19 staging removed. No services or plant state touched.'
else
  echo 'RC19 marker absent; refusing removal' >&2; exit 2
fi
''')
for x in ('install.sh','rollback.sh'): (out/x).chmod(0o755)
# SHA before checks
files=sorted(p for p in out.rglob('*') if p.is_file() and p.name!='SHA256SUMS')
(out/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out)}\n' for p in files))
result=subprocess.run(['python3','-B','-m','unittest','discover','-s','tests','-p','test_*.py','-q'],cwd=out,capture_output=True,text=True)
print('TEST RETURN',result.returncode);print(result.stdout[-1000:]);print(result.stderr[-2000:]);
if result.returncode: raise SystemExit(1)
zipname=Path('/mnt/data/SigenStor_Phase3B_RC19_Commissioning_Handoff.zip')
with zipfile.ZipFile(zipname,'w',zipfile.ZIP_DEFLATED,compresslevel=7) as z:
    for p in sorted(out.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith('.pyc'):
            z.write(p,Path('SigenStor_Phase3B_RC19')/p.relative_to(out))
with zipfile.ZipFile(zipname) as z: print('ZIP CHECK',z.testzip(),'FILES',len(z.namelist()))
print(zipname,zipname.stat().st_size)
