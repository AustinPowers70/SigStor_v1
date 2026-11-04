#!/usr/bin/env python3
"""Phase3B RC3 bounded supervisor engine: injected actuator only; NO plant write entrypoint.

The production CLI cannot instantiate a Modbus actuator. This module accepts an injected
fake in tests to prove expiry, revalidation, sample cadence and handback behaviour.
"""
import dataclasses,datetime as dt,json,math,time
from typing import Callable
import rc13_gateway as gateway

@dataclasses.dataclass(frozen=True)
class Limits:
    max_seconds:int=1800
    poll_seconds:float=2.0
    telemetry_seconds:float=2.0
    max_abs_clock_skew_seconds:float=4.0
    max_telemetry_gap_seconds:float=10.0
    min_reserve_margin_pct:float=2.0
    max_charge_soc_pct:float=95.0

class SessionFailure(RuntimeError):pass

def check_slot(qualification, r6, now):
    if qualification.get('Decision') not in ('GRID_CHARGE','EXPORT') or qualification.get('AuthorityManualReady') is not True:
        raise SessionFailure('no active qualified manual slot')
    slot=r6.get('active_slot') if isinstance(r6,dict) else None
    if not slot:raise SessionFailure('missing R6 slot')
    action=qualification['Decision']
    if slot.get('action')!=action or slot.get('start_utc')!=gateway.timestamp(qualification['StartUtc']).isoformat():
        raise SessionFailure('RC13/R6 mismatch')
    requested=float(qualification['ScheduledEnergyKwh'])
    if not math.isfinite(requested) or requested<=0:raise SessionFailure('invalid energy')
    if abs(float(slot['target_grid_side_kwh'])-requested)>1e-5:raise SessionFailure('grid-side energy mismatch')
    start=gateway.timestamp(qualification['StartUtc']); end=start+dt.timedelta(minutes=30)
    if not start<=now<end:raise SessionFailure('expired slot')
    commissioned_kw=0.5 if action=='GRID_CHARGE' else 0.65
    remaining=(end-now).total_seconds()
    if requested>commissioned_kw*remaining/3600+1e-6:
        raise SessionFailure('energy cannot be delivered within remaining slot at commissioned power')
    return {'action':action,'start_utc':start.isoformat(),'end_utc':end.isoformat(),
            'requested_grid_side_kwh':requested,'commissioned_kw':commissioned_kw,
            'remaining_seconds':remaining,'grid_side_delivery_verified':False}

def run_simulated(*,slot,validate:Callable,plant,telemetry:Callable,record:Callable,
                  utcnow:Callable,monotonic:Callable,sleep:Callable,limits=Limits()):
    """Injected/TEST-only execution engine. Never called by production CLI.
    'plant' must be a fake; no reference to Modbus or commissioned device types.
    """
    start_wall=utcnow(); end= gateway.timestamp(slot['end_utc'])
    if start_wall>=end:raise SessionFailure('slot expired')
    remaining=(end-start_wall).total_seconds()
    duration=min(remaining,limits.max_seconds)
    if duration<=0:raise SessionFailure('no time remains')
    start_tick=monotonic(); deadline=start_tick+duration
    record('PRECHECK',{'slot':slot})
    validate()
    active=False; failure=None; handback_ok=False; sample_count=0; max_gap=0.0
    previous_sample_tick=None
    try:
        active=True # Even an ambiguous first-write error requires recovery
        plant.start(slot['action'])
        record('SESSION_STARTED',{'action':slot['action']})
        while True:
            now_tick=monotonic(); wall=utcnow()
            if now_tick>=deadline or wall>=end:break
            if abs((wall-start_wall).total_seconds()-(now_tick-start_tick))>limits.max_abs_clock_skew_seconds:
                raise SessionFailure('clock discontinuity')
            validate()
            sample=telemetry()
            if not isinstance(sample,dict) or sample.get('valid') is not True:
                raise SessionFailure('invalid in-session telemetry')
            observed=sample.get('observed_utc')
            if observed is None:raise SessionFailure('telemetry timestamp missing')
            observed=gateway.timestamp(observed)
            age=(wall-observed).total_seconds()
            if age< -limits.max_abs_clock_skew_seconds or age>limits.max_telemetry_gap_seconds:
                raise SessionFailure('telemetry stale')
            soc=float(sample['soc_pct']); battery=float(sample['battery_kw'])
            if not math.isfinite(soc) or not math.isfinite(battery):raise SessionFailure('invalid telemetry number')
            if slot['action']=='GRID_CHARGE' and soc>=limits.max_charge_soc_pct:raise SessionFailure('charge SOC ceiling')
            if slot['action']=='EXPORT' and soc<sample['reserve_pct']+limits.min_reserve_margin_pct:
                raise SessionFailure('export reserve margin')
            if previous_sample_tick is not None:
                max_gap=max(max_gap,now_tick-previous_sample_tick)
                if max_gap>limits.max_telemetry_gap_seconds:raise SessionFailure('in-session sample gap')
            previous_sample_tick=now_tick;sample_count+=1
            record('TELEMETRY',{'soc_pct':soc,'battery_kw':battery,'observed_utc':observed.isoformat(),
                                'energy_boundary':'BATTERY_PORT_ONLY'})
            sleep(min(limits.poll_seconds,max(0.0,deadline-monotonic()),
                      max(0.0,(end-utcnow()).total_seconds())))
        record('SLOT_ENDED',{'sample_count':sample_count,'max_sample_gap_s':max_gap})
    except BaseException as exc:
        failure=exc
        record('SESSION_ABORT',{'error':repr(exc)})
    finally:
        if active:
            try:handback_ok=plant.handback() is True
            except BaseException as exc:
                record('HANDBACK_EXCEPTION',{'error':repr(exc)})
        record('HANDBACK_VERIFIED' if handback_ok else 'CRITICAL_HANDBACK_UNVERIFIED',
               {'samples':sample_count})
    if not handback_ok:raise SessionFailure('CRITICAL: verified handback unavailable; local operator recovery required')
    if failure is not None:raise SessionFailure('session aborted; handback verified: '+repr(failure)) from failure
    if sample_count<2:raise SessionFailure('insufficient in-session telemetry; handback verified')
    return {'status':'SIMULATED_COMPLETE_HANDBACK_VERIFIED','samples':sample_count,
            'max_sample_gap_seconds':max_gap,'grid_side_delivery_verified':False,'modbus_writes':0}
