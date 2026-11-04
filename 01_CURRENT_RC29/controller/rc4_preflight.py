#!/usr/bin/env python3
"""RC4 consolidated, read-only preflight with commitment and telemetry boundaries."""
import argparse,datetime as dt,json,sys
from pathlib import Path
import integrated_preview as preview
import slot_commitment as commit
import rc13_gateway as gateway

def report(candidate,settings,authority,r5,db,now):
    baseline=preview.evaluate(candidate,settings,authority,r5,db,now)
    out={'schema':'SIGEN_PHASE3B_RC4_PREFLIGHT','created_utc':now.isoformat(),
         'production_execution_enabled':False,'autonomous_dispatch':False,'modbus_writes':0,
         'operator_approval_required':True,'grid_side_delivery_verified':False,
         'integration_readiness':baseline['readiness'],
         'battery_port_evidence':baseline.get('battery_port_evidence'),
         'readiness':'HOLD','reason':baseline['readiness']}
    if baseline['readiness']!='PREVIEW_MATCHED_NO_EXECUTION':return out
    q=baseline['qualification']
    try:
        c=commit.calculate(action=q['Decision'],start_utc=q['StartUtc'],
            scheduled_kwh=q['ScheduledEnergyKwh'],now=now)
        out.update({'slot_commitment':c,'reason':c['state'],'readiness':'OFFLINE_SLOT_QUALIFIED_LIVE_GATED'})
    except (ValueError,TypeError,KeyError) as e:out['reason']='FAIL_CLOSED '+str(e)
    return out

def main(argv=None):
    p=argparse.ArgumentParser(description='RC4 read-only unified preflight; no Modbus writes')
    p.add_argument('--candidate',type=Path,default=gateway.DOC)
    p.add_argument('--settings',type=Path,default=gateway.SET)
    p.add_argument('--authority',type=Path,default=gateway.AUTH)
    p.add_argument('--r5',type=Path,default=preview.DEFAULT_R5)
    p.add_argument('--db',type=Path,default=preview.DEFAULT_DB)
    p.add_argument('--execute-slot',action='store_true',help='always blocked')
    a=p.parse_args(argv)
    if a.execute_slot:
        print('BLOCKED: live full-slot writes not approved; MODBUS_WRITES=0');return 2
    try:
        out=report(preview.read(a.candidate),preview.read(a.settings),preview.read(a.authority),
            preview.read(a.r5),a.db if a.db.is_file() else None,dt.datetime.now(dt.timezone.utc))
        print(json.dumps(out,sort_keys=True,indent=2,allow_nan=False));return 0
    except Exception as exc:
        print('PHASE3B_RC4_FAIL_CLOSED',type(exc).__name__,str(exc),'MODBUS_WRITES=0');return 2
if __name__=='__main__':sys.exit(main())
