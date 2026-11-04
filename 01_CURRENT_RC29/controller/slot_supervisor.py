#!/usr/bin/env python3
"""Phase 3B: read-only slot qualification and bounded execution planning.
Never imports an actuator and never opens Modbus for writes.
Full-duration dispatch NOT authorised in this release candidate.
"""
import argparse,json,math,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
import rc13_gateway as gateway

CHARGE_KW=0.5 # commissioned 40032=500, not a claim of grid-side delivery
EXPORT_KW=0.65 # previously commissioned export pilot only
MAX_WINDOW_SECONDS=1800

def plan(doc,settings,authority,now):
    result=gateway.validate(doc,settings,authority,now)
    result=dict(result)
    decision=result['Decision']
    result.update({'ExecutionEnabled':False,'ModbusWrites':0,'PhysicalGridEnergyVerified':False})
    if decision not in ('GRID_CHARGE','EXPORT'):
        result['Reason']='No currently qualified actionable slot'
        return result
    start=gateway.timestamp(result['StartUtc']); end=start+timedelta(seconds=MAX_WINDOW_SECONDS)
    remaining=max(0,(end-now).total_seconds())
    kw=CHARGE_KW if decision=='GRID_CHARGE' else EXPORT_KW
    available=remaining*kw/3600
    amount=float(result['ScheduledEnergyKwh'])
    if not math.isfinite(amount) or amount<=0:raise ValueError('invalid scheduled energy')
    result.update({'SlotEndUtc':end.isoformat(),'RemainingSeconds':round(remaining,3),
        'CommissionedPowerKw':kw,'RemainingMaximumEnergyKwh':round(available,5),
        'RequestedEnergyKwh':amount,'CanDeliverWithinRemainingSlot':amount<=available+1e-8,
        'Reason':'FULL_SLOT_LIVE_GATE_CLOSED; calibrated grid-side measurement and signed-off setpoint contract required'})
    return result

def load(path):
    if path.is_symlink() or not path.is_file():raise ValueError('unsafe or missing input '+str(path))
    return json.loads(path.read_text())

def main(argv=None):
    p=argparse.ArgumentParser(description='Read-only Phase 3B slot preview, never dispatches')
    p.add_argument('--candidate',type=Path,default=gateway.DOC)
    p.add_argument('--settings',type=Path,default=gateway.SET)
    p.add_argument('--authority',type=Path,default=gateway.AUTH)
    p.add_argument('--execute-slot',action='store_true',help='reserved, intentionally blocked')
    a=p.parse_args(argv)
    if a.execute_slot:
        print('BLOCKED: full-slot Modbus writes not qualified; MODBUS_WRITES=0');return 2
    try:
        print(json.dumps(plan(load(a.candidate),load(a.settings),load(a.authority),datetime.now(timezone.utc)),indent=2,sort_keys=True))
        return 0
    except (ValueError,KeyError,TypeError,OSError,OverflowError) as e:
        print('FAIL_CLOSED: '+str(e)+'; MODBUS_WRITES=0');return 2
if __name__=='__main__':sys.exit(main())
