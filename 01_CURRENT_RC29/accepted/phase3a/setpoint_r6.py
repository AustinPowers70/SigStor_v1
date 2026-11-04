#!/usr/bin/env python3
"""Non-dispatching R6: source-pinned grid-side setpoint preview and measurement math."""
import argparse, datetime as dt, importlib.util, json, math, os, tempfile
from pathlib import Path
R5=Path('/opt/sigenstor/scripts/phase3a/contract_verified_r5.py')
OUT=Path('/opt/sigenstor/data/rtm/phase3a-setpoints-r6.json')
MAX_W=8000

def iso(x):
    v=dt.datetime.fromisoformat(x.replace('Z','+00:00'))
    if v.tzinfo is None:raise ValueError('naive time')
    return v.astimezone(dt.timezone.utc)

def convert_slot(slot):
    kind=slot['action']; energy=slot['grid_side_kwh']; kw=slot['average_grid_side_kw']
    if kind not in ('HOLD','GRID_CHARGE','EXPORT'):raise ValueError('unknown action')
    if any(type(x) not in (float,int) or not math.isfinite(x) for x in (energy,kw)):raise ValueError('bad numbers')
    if energy<0 or kw<0 or kw>8 or abs(kw-2*energy)>1e-5:raise ValueError('power/energy conflict')
    if kind=='HOLD' and (energy!=0 or kw!=0):raise ValueError('nonzero hold')
    if kind!='HOLD' and energy<=0:raise ValueError('empty dispatch action')
    start,end=iso(slot['start_utc']),iso(slot['end_utc'])
    if (end-start).total_seconds()!=1800:raise ValueError('slot duration')
    watts=round(kw*1000)
    if watts>MAX_W:raise ValueError('hardware power')
    # NO Modbus register mapping: battery charging limit and PCS export have different contracts.
    return {'start_utc':start.isoformat(),'end_utc':end.isoformat(),'action':kind,
            'target_grid_side_kwh':round(energy,6),'nominal_grid_side_watts':watts,
            'physical_setpoint_verified':False,'dispatch_permitted':False}

def reconcile_meter(samples,kind):
    """Pure math for independently measured *battery-port/grid-side* signed power.
    Samples (utc_timestamp, measured_grid_side_kw), +charge and -export.
    Reject gaps >120 seconds; no house-import measurements accepted as battery flow.
    """
    if kind not in ('GRID_CHARGE','EXPORT'):raise ValueError('invalid mode')
    if len(samples)<2:raise ValueError('insufficient measured samples')
    points=[(iso(t),p) for t,p in samples]
    total=0.0
    for (ta,pa),(tb,pb) in zip(points,points[1:]):
        if any(type(p) not in (int,float) or not math.isfinite(p) or abs(p)>8.5 for p in (pa,pb)):
            raise ValueError('invalid measured power')
        secs=(tb-ta).total_seconds()
        if secs<=0 or secs>120:raise ValueError('measurement gap / order')
        signed=(pa+pb)/2
        if (kind=='GRID_CHARGE' and signed < -0.05) or (kind=='EXPORT' and signed > 0.05):
            raise ValueError('measured flow contradicts commanded direction')
        total+=abs(signed)*secs/3600
    return round(total,6)

def build(src,now):
    if src.get('schema')!='SIGEN_PHASE3A_VERIFIED_ENVELOPE_R5' or src.get('contract_verified') is not True or src.get('contract')!='GRID_SIDE_CHARGE_AND_EXPORT_KWH':raise ValueError('unverified source')
    if src.get('execution_authorised') is not False or src.get('autonomous_dispatch') is not False:raise ValueError('unexpected dispatch flag')
    if not -120 <= (now-iso(src['source_snapshot_utc'])).total_seconds() <= 600:
        # source gating must not be bypassed even if R5 recomputation is changed
        raise ValueError('stale source')
    slots=[convert_slot(s) for s in src['slots']]
    active=[s for s in slots if iso(s['start_utc'])<=now<iso(s['end_utc'])]
    if len(active)>1:raise ValueError('overlapping slots')
    return {'schema':'SIGEN_PHASE3A_SETPOINT_PREVIEW_R6','created_utc':now.isoformat(),
            'source_snapshot_utc':src['source_snapshot_utc'],'contract':'GRID_SIDE_KWH_TO_WATTS',
            'source_solver_sha256':src['source_sha256'],'active_slot':active[0] if active else None,
            'slot_count':len(slots),'slots':slots,'measurement_status':'NOT_AVAILABLE_NO_MEASURED_BATTERY_FLOW',
            'physical_setpoint_verified':False,'dispatch_permitted':False,'autonomous_dispatch':False,
            'modbus_writes':0}

def write(path,body):
    if path.is_symlink():raise ValueError('symlink destination')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.phase3a-r6-')
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(body,f,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o644);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--publish',action='store_true');ap.add_argument('--status',action='store_true');args=ap.parse_args()
    if not(args.status or args.publish):ap.error('choose --status or --publish')
    try:
        spec=importlib.util.spec_from_file_location('r5_contract',R5)
        if R5.is_symlink() or not R5.is_file():raise ValueError('missing R5')
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        now=dt.datetime.now(dt.timezone.utc)
        result=build(mod.compute(now),now)
        if args.publish:write(OUT,result)
        print(json.dumps({k:v for k,v in result.items() if k!='slots'},sort_keys=True))
        print('PHASE3A_R6_SETPOINT_PREVIEW_READY_NO_MODBUS_WRITES');return 0
    except Exception as exc:
        print('PHASE3A_R6_HOLD_BLOCKED',type(exc).__name__,str(exc),'NO_MODBUS_WRITES');return 2
if __name__=='__main__':raise SystemExit(main())
