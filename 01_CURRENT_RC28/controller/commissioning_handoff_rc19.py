#!/usr/bin/env python3
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
                    f.write(output+'\n');f.flush();os.fsync(f.fileno())
                os.replace(temp,args.out)
            finally:
                if os.path.exists(temp):os.unlink(temp)
        print(output)
        return 0 # HOLD is an expected readiness result; never an execution success
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
        print('RC19_FAIL_CLOSED',type(exc).__name__,str(exc),'MODBUS_WRITES=0');return 2
if __name__=='__main__':raise SystemExit(main())
