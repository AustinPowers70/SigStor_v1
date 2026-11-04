#!/usr/bin/env python3
"""RC10 qualified-slot observational runner. NO ACTUATOR / NO CONTROL WRITES.

Preflight is repeated before each read, with immutable source fingerprint.
The sampler and time sources are injected for offline fault-injection testing.
"""
import argparse,datetime as dt,json,math,sys,time
from pathlib import Path
import rc13_gateway
import integrated_preview
import session_integration_rc5 as integration
import power_acquisition_rc9 as power
import commissioning_evidence

class ObservationError(RuntimeError): pass

def preflight(now, candidate=None,settings=None,authority=None,r5=None):
    paths=(candidate or rc13_gateway.DOC,settings or rc13_gateway.SET,authority or rc13_gateway.AUTH,r5 or integrated_preview.DEFAULT_R5)
    docs=[integrated_preview.read(Path(p)) for p in paths]
    return integration.prepare(*docs,now)

def observe(*,plan,qualify,read,sample_write,clock=time.monotonic,utcnow=None,sleep=time.sleep,
            maximum_seconds=60,interval_seconds=2,maximum_gap_seconds=10):
    if plan.get('state')!='QUALIFIED_SIMULATION_ONLY' or plan.get('dispatch_enabled') is not False:
        raise ObservationError('qualified advisory plan required')
    if not 1<=maximum_seconds<=1800 or not 1<=interval_seconds<=10 or maximum_gap_seconds<interval_seconds:
        raise ObservationError('invalid bounds')
    utcnow=utcnow or (lambda:dt.datetime.now(dt.timezone.utc))
    start_wall=utcnow();start_tick=clock();end=rc13_gateway.timestamp(plan['end_utc'])
    if start_wall.tzinfo is None or not start_wall<end: raise ObservationError('expired or naive clock')
    deadline=min(start_tick+maximum_seconds,start_tick+(end-start_wall).total_seconds())
    samples=[];last_tick=None;termination='DURATION_LIMIT'
    while clock()<deadline:
        tick=clock();now=utcnow()
        if now.tzinfo is None or abs((now-start_wall).total_seconds()-(tick-start_tick))>4: raise ObservationError('clock discontinuity')
        if now>=end:termination='SLOT_EXPIRED';break
        current=qualify(now)
        for name in ('state','action','start_utc','end_utc','source_fingerprint'):
            if current.get(name)!=plan.get(name): raise ObservationError('qualification changed: '+name)
        if last_tick is not None and tick-last_tick>maximum_gap_seconds:raise ObservationError('sampling gap')
        values=read()
        for field in ('soc_pct','battery_kw','grid_kw','pv_kw','home_kw'):
            if field not in values or isinstance(values[field],bool) or not math.isfinite(float(values[field])):
                raise ObservationError('invalid power sample')
        soc=float(values['soc_pct']);reserve=0
        if not 0<=soc<=100:raise ObservationError('SOC outside limits')
        if plan['action']=='GRID_CHARGE' and soc>=95:raise ObservationError('charge ceiling')
        # Export reserve is validated by qualify() and the pinned RC13 snapshot.
        # This OBSERVATION-ONLY mode does not command or maintain export.
        row={'schema':'SIGEN_PHASE3B_RC10_OBSERVATION','timestamp_utc':now.astimezone(dt.timezone.utc).isoformat(),
             'valid':True,'action':plan['action'],'battery_grid_side_delivery_verified':False,
             'energy_boundary':'BATTERY_PORT_AND_AGGREGATE_GRID_ONLY','modbus_writes':0,
             **{k:float(values[k]) for k in ('soc_pct','battery_kw','grid_kw','pv_kw','home_kw')}}
        sample_write(row)
        samples.append(row);last_tick=tick
        remaining=min(deadline-clock(),(end-utcnow()).total_seconds())
        if remaining<=0:break
        sleep(min(remaining,interval_seconds))
    return {'schema':'SIGEN_PHASE3B_RC10_OBSERVATION_RESULT','status':'OBSERVED_NO_DISPATCH',
            'termination':termination,'samples':len(samples),'first_sample_utc':samples[0]['timestamp_utc'] if samples else None,
            'last_sample_utc':samples[-1]['timestamp_utc'] if samples else None,
            'grid_side_delivery_verified':False,'autonomous_dispatch':False,'modbus_writes':0}

def main(argv=None):
    p=argparse.ArgumentParser(description='Qualified-slot read-only observation; no actuation')
    p.add_argument('--seconds',type=int,default=60)
    p.add_argument('--interval-seconds',type=float,default=2)
    p.add_argument('--out',type=Path,default=Path('/opt/sigenstor/data/rtm/phase3b-rc10-observation.jsonl'))
    p.add_argument('--execute-slot',action='store_true')
    args=p.parse_args(argv)
    if args.execute_slot:
        print('BLOCKED: RC10 has no full-slot actuator; MODBUS_WRITES=0');return 2
    try:
        now=dt.datetime.now(dt.timezone.utc);plan=preflight(now)
        if plan.get('state')!='QUALIFIED_SIMULATION_ONLY':
            print(json.dumps({'readiness':'HOLD_NO_QUALIFIED_SLOT','preflight':plan,'modbus_writes':0},sort_keys=True));return 0
        outcome=observe(plan=plan,qualify=preflight,read=power.sample_once,
                        sample_write=lambda row:power.append(args.out,row),
                        maximum_seconds=args.seconds,interval_seconds=args.interval_seconds)
        print(json.dumps(outcome,sort_keys=True));return 0
    except (ValueError,RuntimeError,TypeError,KeyError,OSError) as exc:
        print('PHASE3B_RC10_FAIL_CLOSED',type(exc).__name__,str(exc),'MODBUS_WRITES=0');return 2
if __name__=='__main__':sys.exit(main())
