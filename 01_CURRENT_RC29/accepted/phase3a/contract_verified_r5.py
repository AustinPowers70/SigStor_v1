#!/usr/bin/env python3
"""Phase 3A R5 source-pinned accounting contract and read-only execution envelope."""
import argparse, datetime as dt, hashlib, importlib.util, json, math, os, tempfile
from pathlib import Path
ROOT=Path('/opt/sigenstor/scripts')
SOLVER=ROOT/'rtm_v12_unified_candidate.py'
R1=ROOT/'phase3a/slot_plan_r1.py'
R2=ROOT/'phase3a/execution_envelope_r2.py'
OUTPUT=Path('/opt/sigenstor/data/rtm/phase3a-verified-envelope-r5.json')
SOLVER_SHA='8f84867f7b97a221aab488b3b9a7e2f33b186fa77c94b867c514389db09d4cad'
# Source-pinned contract: C/X are grid-side kWh, E is stored battery kWh,
# eta is the one-way conversion factor. Double efficiency conversion forbidden.
CONTRACT='GRID_SIDE_CHARGE_AND_EXPORT_KWH'

def import_module(name,path):
    if path.is_symlink() or not path.is_file():raise RuntimeError('missing/unsafe module '+str(path))
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj

def verify_solver(raw,sha=SOLVER_SHA):
    if hashlib.sha256(raw).hexdigest()!=sha:raise RuntimeError('RC13_SOLVER_SOURCE_CHANGED_REVIEW_REQUIRED')
    s=raw.decode('utf-8')
    required=('energy={E+i:1,C+i:-ETA,H+i:1/ETA,X+i:1/ETA}',
              'calculated=last+ETA*c-(h+ex)/ETA',
              "'GridChargeKwh':round(c,6)","'GridExportKwh':round(ex,6)")
    if not all(x in s for x in required):raise RuntimeError('RC13_ACCOUNTING_EQUATIONS_CHANGED')
    return True

def compile_verified(plan, envelope, now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if plan.get('schema')!='SIGEN_PHASE3A_SLOT_PLAN_R1' or envelope.get('schema')!='SIGEN_PHASE3A_EXECUTION_ENVELOPE_R2':raise ValueError('invalid inputs')
    if envelope.get('contract_verified') is not True:raise ValueError('R2 contract not asserted')
    if envelope.get('execution_authorised') is not False:raise ValueError('unapproved execution')
    if plan.get('source_snapshot_utc')!=envelope.get('source_snapshot_utc'):raise ValueError('source mismatch')
    items=[]
    for slot in plan['slots']:
        action=slot['action']; kwh=slot['grid_energy_kwh']; kw=slot['nominal_grid_kw']
        if action not in ('GRID_CHARGE','EXPORT','HOLD'):raise ValueError('unknown action')
        if type(kwh) not in (int,float) or type(kw) not in (int,float) or not all(math.isfinite(v) for v in (kwh,kw)):raise ValueError('invalid numeric field')
        if kwh<0 or kw<0 or kw>8.0 or abs(kw-2*kwh)>0.00001:raise ValueError('invalid grid power')
        items.append({'start_utc':slot['start_utc'],'end_utc':slot['end_utc'],'action':action,'grid_side_kwh':kwh,'average_grid_side_kw':kw})
    result={'schema':'SIGEN_PHASE3A_VERIFIED_ENVELOPE_R5','timestamp_utc':now.isoformat(),
      'source_snapshot_utc':plan['source_snapshot_utc'],'contract':CONTRACT,'contract_verified':True,
      'source_sha256':SOLVER_SHA,'efficiency_applied_to_grid_setpoint':False,'slots':items,
      'active_slot':envelope.get('active_slot'),'execution_authorised':False,
      'autonomous_dispatch':False,'modbus_writes':0,'reason':envelope.get('reason')}
    return result

def compute(now=None):
    if SOLVER.is_symlink() or not SOLVER.is_file():raise RuntimeError('solver missing/unsafe')
    verify_solver(SOLVER.read_bytes())
    r1=import_module('phase3a_r1',R1)
    r2=import_module('phase3a_r2',R2)
    now=now or dt.datetime.now(dt.timezone.utc)
    plan=r1.compile_plan(r1.safe_read(r1.DOC),r1.safe_read(r1.SET),r1.safe_read(r1.AUTH),now=now)
    envelope=r2.validate_envelope(plan,now=now,verified_grid_side_contract=True)
    return compile_verified(plan,envelope,now)

def publish(result,path=OUTPUT):
    if path.is_symlink():raise RuntimeError('symlink output')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.phase3a-r5-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(result,f,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o644);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--publish',action='store_true');ap.add_argument('--status',action='store_true');args=ap.parse_args(argv)
    if not (args.publish or args.status):ap.error('choose --publish or --status')
    try:
        result=compute()
        if args.publish:publish(result)
        print(json.dumps({k:v for k,v in result.items() if k!='slots'},sort_keys=True))
        print('PHASE3A_R5_GRID_SIDE_CONTRACT_VERIFIED_NO_MODBUS_WRITES');return 0
    except Exception as exc:
        print('PHASE3A_R5_CONTRACT_BLOCKED',type(exc).__name__,str(exc),'NO_MODBUS_WRITES');return 2
if __name__=='__main__':raise SystemExit(main())
