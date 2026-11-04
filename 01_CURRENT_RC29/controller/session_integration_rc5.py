#!/usr/bin/env python3
"""RC5 fail-closed integration seam. Offline dry run only; no production actuator.

The accepted 30-second commissioned routines are *not* repurposed as full-slot
actuators. No Modbus connection is made by this module.
"""
import dataclasses, datetime as dt, hashlib, json, math, time
from typing import Callable
import rc13_gateway
import slot_commitment

class IntegrationError(RuntimeError): pass

@dataclasses.dataclass(frozen=True)
class Policy:
    max_session_seconds: int = 1800
    max_sample_gap_seconds: float = 10
    max_skew_seconds: float = 4
    charge_stop_soc_pct: float = 95
    export_reserve_margin_pct: float = 2
    min_samples: int = 2

def source_fingerprint(doc, setting, authority, r5):
    canonical=json.dumps([doc,setting,authority,r5],sort_keys=True,allow_nan=False,separators=(',',':')).encode()
    return hashlib.sha256(canonical).hexdigest()

def prepare(doc,setting,authority,r5,now):
    """Authoritative READ-ONLY handoff: require RC13 and verified R5/R6 agreement."""
    import integrated_preview
    result=integrated_preview.evaluate(doc,setting,authority,r5,None,now)
    if result['readiness']!='PREVIEW_MATCHED_NO_EXECUTION':
        return {'state':'HOLD','reason':result['readiness'],'modbus_writes':0,'dispatch_enabled':False}
    q=result['qualification']
    c=slot_commitment.calculate(action=q['Decision'],start_utc=q['StartUtc'],
                                scheduled_kwh=q['ScheduledEnergyKwh'],now=now)
    return {'state':'QUALIFIED_SIMULATION_ONLY','action':q['Decision'],
            'start_utc':c['slot_start_utc'],'end_utc':c['slot_end_utc'],
            'scheduled_grid_side_kwh':c['scheduled_grid_side_kwh'],
            'rated_kw':c['commissioned_kw'],'source_fingerprint':source_fingerprint(doc,setting,authority,r5),
            'evidence_boundary':'BATTERY_PORT_NOT_VERIFIED_GRID_SIDE',
            'modbus_writes':0,'dispatch_enabled':False}

def run_offline(*,plan,read_sources:Callable,read_telemetry:Callable,simulator,
                utcnow:Callable,monotonic:Callable,sleep:Callable,audit:Callable,
                policy=Policy()):
    """Deterministic simulation of a qualified slot; simulator must be an injected fake.

    Any write-capable adapter is expressly rejected. This mode cannot authorise plant control.
    """
    if plan.get('state')!='QUALIFIED_SIMULATION_ONLY' or plan.get('dispatch_enabled') is not False:
        raise IntegrationError('not a simulation-only qualified plan')
    if not getattr(simulator,'simulation_only',False):
        raise IntegrationError('live actuator prohibited')
    end=rc13_gateway.timestamp(plan['end_utc'])
    start_wall=utcnow(); start_tick=monotonic()
    if start_wall>=end:raise IntegrationError('slot expired')
    duration=min(policy.max_session_seconds,(end-start_wall).total_seconds())
    deadline=start_tick+duration
    samples=0; last_sample_tick=None; max_gap=0.; failure=None; handback_ok=False; entered=False
    audit('PRECHECK',{'fingerprint':plan['source_fingerprint'],'modbus_writes':0})
    def validate():
        current=read_sources()
        if current.get('state')!='QUALIFIED_SIMULATION_ONLY' or current.get('source_fingerprint')!=plan['source_fingerprint']:
            raise IntegrationError('qualified source changed or stale')
        if current.get('start_utc')!=plan['start_utc'] or current.get('action')!=plan['action']:
            raise IntegrationError('slot/action changed')
    validate()
    try:
        entered=True
        simulator.start(plan['action'],plan['rated_kw'])
        audit('SIMULATED_START',{'action':plan['action'],'rated_kw':plan['rated_kw']})
        while True:
            tick=monotonic(); wall=utcnow()
            if abs((wall-start_wall).total_seconds()-(tick-start_tick))>policy.max_skew_seconds:
                raise IntegrationError('clock jump')
            if tick>=deadline or wall>=end:break
            validate()
            sample=read_telemetry()
            if sample.get('valid') is not True:raise IntegrationError('invalid telemetry')
            stamp=rc13_gateway.timestamp(sample['observed_utc'])
            age=(wall-stamp).total_seconds()
            if age < -policy.max_skew_seconds or age>policy.max_sample_gap_seconds:
                raise IntegrationError('stale telemetry')
            soc=float(sample['soc_pct']); battery=float(sample['battery_kw']); reserve=float(sample['reserve_pct'])
            if not all(math.isfinite(v) for v in (soc,battery,reserve)) or not 0<=soc<=100:
                raise IntegrationError('invalid SOC/power/reserve')
            if plan['action']=='GRID_CHARGE' and soc>=policy.charge_stop_soc_pct:
                raise IntegrationError('charge ceiling')
            if plan['action']=='EXPORT' and soc<reserve+policy.export_reserve_margin_pct:
                raise IntegrationError('export reserve floor')
            if last_sample_tick is not None:
                max_gap=max(max_gap,tick-last_sample_tick)
                if max_gap>policy.max_sample_gap_seconds:raise IntegrationError('telemetry gap')
            last_sample_tick=tick; samples+=1
            audit('SAMPLE',{'soc_pct':soc,'battery_kw':battery,'energy_boundary':'BATTERY_PORT_ONLY'})
            sleep(min(2, max(0,deadline-monotonic()),max(0,(end-utcnow()).total_seconds())))
        audit('SIMULATED_SLOT_END',{'samples':samples})
    except BaseException as exc:
        failure=exc
        audit('SIMULATED_ABORT',{'error':repr(exc)})
    finally:
        if entered:
            try:handback_ok=simulator.handback() is True
            except BaseException as exc:audit('HANDBACK_EXCEPTION',{'error':repr(exc)})
        audit('SIMULATED_HANDBACK_VERIFIED' if handback_ok else 'CRITICAL_SIMULATED_HANDBACK_UNVERIFIED',{'samples':samples})
    if not handback_ok:raise IntegrationError('simulated handback unverified')
    if failure is not None:raise IntegrationError('simulated session aborted: '+repr(failure)) from failure
    if samples<policy.min_samples:raise IntegrationError('insufficient in-session samples')
    return {'status':'SIMULATED_COMPLETE','samples':samples,'max_sample_gap_seconds':max_gap,
            'grid_side_delivery_verified':False,'modbus_writes':0}
