#!/usr/bin/env python3
"""Offline-only RC3 readiness report; no Modbus actuator imports or calls."""
import argparse,datetime as dt,json,sys
from pathlib import Path
import integrated_preview as preview
import bounded_session as engine
import rc13_gateway as gateway

def report(candidate,settings,authority,r5,db,now):
    baseline=preview.evaluate(candidate,settings,authority,r5,db,now)
    gate={'schema':'SIGEN_PHASE3B_RC3_READINESS','created_utc':now.isoformat(),
          'production_execution_enabled':False,'operator_approval_required':True,
          'autonomous_dispatch':False,'modbus_writes':0,
          'readiness':'HOLD','grid_side_delivery_verified':False,
          'battery_port_evidence':baseline.get('battery_port_evidence'),
          'integration_readiness':baseline['readiness']}
    if baseline['readiness']!='PREVIEW_MATCHED_NO_EXECUTION':
        gate['reason']=baseline['readiness'];return gate
    try:
        r6=preview.module(preview.R6,'phase3b_rc3_r6').build(r5,now)
        slot=engine.check_slot(baseline['qualification'],r6,now)
        gate['slot']=slot;gate['readiness']='SIMULATION_READY_LIVE_EXECUTION_BLOCKED'
        gate['reason']='Live control and independent grid-side measurement not commissioned'
    except (ValueError,KeyError,TypeError,engine.SessionFailure) as exc:
        gate['reason']='FAIL_CLOSED '+str(exc)
    return gate

def main(argv=None):
    p=argparse.ArgumentParser(description='Phase3B RC3 offline readiness; never dispatch')
    p.add_argument('--candidate',type=Path,default=gateway.DOC)
    p.add_argument('--settings',type=Path,default=gateway.SET)
    p.add_argument('--authority',type=Path,default=gateway.AUTH)
    p.add_argument('--r5',type=Path,default=preview.DEFAULT_R5)
    p.add_argument('--db',type=Path,default=preview.DEFAULT_DB)
    p.add_argument('--execute-slot',action='store_true')
    args=p.parse_args(argv)
    if args.execute_slot:
        print('BLOCKED: RC3 live Modbus actuation not enabled; MODBUS_WRITES=0');return 2
    try:
        out=report(preview.read(args.candidate),preview.read(args.settings),
                   preview.read(args.authority),preview.read(args.r5),args.db if args.db.is_file() else None,
                   dt.datetime.now(dt.timezone.utc))
        print(json.dumps(out,sort_keys=True,indent=2));return 0
    except Exception as e:
        print('PHASE3B_RC3_FAIL_CLOSED',type(e).__name__,str(e),'MODBUS_WRITES=0');return 2
if __name__=='__main__':sys.exit(main())
