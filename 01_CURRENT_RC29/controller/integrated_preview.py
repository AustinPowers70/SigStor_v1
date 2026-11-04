#!/usr/bin/env python3
"""Phase3B RC2 integrated advisory-only slot and telemetry reconciliation.
No actuation, no service changes, no background dispatch. RC13 remains unmodified.
"""
import argparse, datetime as dt, hashlib, importlib.util, json, os, sys, tempfile
from pathlib import Path
import rc13_gateway as gateway
import slot_supervisor as supervisor

BASE=Path(__file__).resolve().parents[1]
R6=BASE/'accepted/phase3a/setpoint_r6.py'
R9=BASE/'accepted/phase3a/telemetry_sqlite_r9.py'
R10=BASE/'accepted/phase3a/session_energy_r10.py'
R5=BASE/'accepted/phase3a/contract_verified_r5.py'
DEFAULT_R5=Path('/opt/sigenstor/data/rtm/phase3a-verified-envelope-r5.json')
DEFAULT_DB=Path('/opt/sigenstor/data/HouseholdTelemetry.sqlite')

def module(path,name):
    if path.is_symlink() or not path.is_file(): raise ValueError('missing/untrusted bundled module')
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj

def read(path):
    if path.is_symlink() or not path.is_file():raise ValueError('missing or symlink input: '+str(path))
    return json.loads(path.read_text())

def evaluate(doc,settings,authority,r5,db,now):
    result=supervisor.plan(doc,settings,authority,now)
    output={'schema':'SIGEN_PHASE3B_RC2_INTEGRATED_PREVIEW','created_utc':now.isoformat(),
            'qualification':result,'execution_enabled':False,'autonomous_dispatch':False,
            'modbus_writes':0,'grid_side_delivery_verified':False,
            'grid_side_contract':'GRID_SIDE_CHARGE_AND_EXPORT_KWH',
            'battery_port_evidence':None,'r5_r6_contract':None,'readiness':'HOLD'}
    r6=module(R6,'phase3b_r6');module(R5,'phase3b_r5')
    if r5 is not None:
        spec=r6.build(r5,now)
        active=spec['active_slot']
        output['r5_r6_contract']={'source_sha256':spec['source_solver_sha256'],
            'active_slot':active,'dispatch_permitted':False,'physical_setpoint_verified':False}
        if result['Decision'] in ('GRID_CHARGE','EXPORT'):
            if active is None:output['readiness']='HOLD_NO_R5_R6_ACTIVE_SLOT'
            else:
                matches=(active['action']==result['Decision'] and
                         active['start_utc']==gateway.timestamp(result['StartUtc']).isoformat() and
                         abs(active['target_grid_side_kwh']-result['RequestedEnergyKwh'])<=0.00001)
                output['readiness']='PREVIEW_MATCHED_NO_EXECUTION' if matches else 'HOLD_R5_RC13_MISMATCH'
        else:output['readiness']='HOLD_NO_ACTION'
    else:output['readiness']='HOLD_MISSING_R5_CONTRACT'
    if db is not None:
        try:
            r9=module(R9,'phase3b_r9'); evidence=r9.collect(db,now=now,hours=1)
            output['battery_port_evidence']={k:evidence[k] for k in (
                'state','sample_count','latest_sample_utc','latest_sample_age_seconds',
                'battery_port_charge_kwh','battery_port_discharge_kwh','energy_boundary')}
        except (OSError,ValueError,RuntimeError) as e:
            output['battery_port_evidence']={'state':'UNAVAILABLE','reason':str(e)}
    output['execution_block_reason']='SUPERVISED_FULL_SLOT_CONTROL_NOT_COMMISSIONED; GRID_SIDE_PHYSICAL_DELIVERY_UNVERIFIED'
    return output

def session_energy(db,start,end,action,planned,now):
    r10=module(R10,'phase3b_r10')
    return r10.evaluate(db,gateway.timestamp(start),gateway.timestamp(end),action,planned,now)

def write_atomic(path,obj):
    if path.is_symlink():raise ValueError('unsafe output symlink')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.phase3b-rc2-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(obj,f,sort_keys=True,allow_nan=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o640);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def main(argv=None):
    p=argparse.ArgumentParser(description='Phase3B integrated READ ONLY preview and evidence')
    p.add_argument('--candidate',type=Path,default=gateway.DOC)
    p.add_argument('--settings',type=Path,default=gateway.SET)
    p.add_argument('--authority',type=Path,default=gateway.AUTH)
    p.add_argument('--r5',type=Path,default=DEFAULT_R5)
    p.add_argument('--db',type=Path,default=DEFAULT_DB)
    p.add_argument('--out',type=Path)
    p.add_argument('--execute-slot',action='store_true',help='intentionally unavailable')
    p.add_argument('--session-start-utc');p.add_argument('--session-end-utc')
    p.add_argument('--session-action',choices=['GRID_CHARGE','EXPORT','HOLD'])
    p.add_argument('--planned-grid-kwh',type=float)
    a=p.parse_args(argv)
    if a.execute_slot:
        print('BLOCKED: full-slot Modbus execution not commissioned; MODBUS_WRITES=0');return 2
    try:
        now=dt.datetime.now(dt.timezone.utc)
        if a.session_start_utc or a.session_end_utc or a.session_action:
            if not (a.session_start_utc and a.session_end_utc and a.session_action):raise ValueError('incomplete session parameters')
            output=session_energy(a.db,a.session_start_utc,a.session_end_utc,a.session_action,a.planned_grid_kwh,now)
        else:
            output=evaluate(read(a.candidate),read(a.settings),read(a.authority),
                            read(a.r5) if a.r5.is_file() else None,
                            a.db if a.db.is_file() else None,now)
        if a.out:write_atomic(a.out,output)
        print(json.dumps(output,sort_keys=True,indent=2));return 0
    except Exception as e:
        print('PHASE3B_RC2_FAIL_CLOSED',type(e).__name__,str(e),'MODBUS_WRITES=0');return 2
if __name__=='__main__':sys.exit(main())
