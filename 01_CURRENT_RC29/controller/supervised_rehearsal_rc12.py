#!/usr/bin/env python3
"""RC12 cohesive full-slot rehearsal. SIMULATION ONLY; never Modbus writes.

Models exclusive authority, continuous observation and mandatory handback as
one transaction. Injected collaborators must all be simulation-only. Not a live
commissioning command, a replacement for inverter-native safety, or a release
of the existing 30-second pilot limitation.
"""
import datetime as dt, math, time
import rc13_gateway

class RehearsalError(RuntimeError): pass
PINNED=('state','action','start_utc','end_utc','source_fingerprint','rated_kw')

def run(*,plan,lock,panel,actuator,qualify,sample,record,utcnow,clock,sleep,
        duration_cap=1800,interval=2,max_gap=10,max_skew=4,reserve_margin=2):
    if plan.get('state')!='QUALIFIED_SIMULATION_ONLY' or plan.get('dispatch_enabled') is not False:
        raise RehearsalError('qualified simulation-only plan required')
    if not all(getattr(obj,'simulation_only',False) is True for obj in (lock,panel,actuator)):
        raise RehearsalError('live authority/lock/actuator prohibited')
    if not 0<duration_cap<=1800 or not 0<interval<=10 or not interval<=max_gap<=60:
        raise RehearsalError('invalid bounds')
    end=rc13_gateway.timestamp(plan['end_utc'])
    start_wall=utcnow();start_tick=clock()
    if start_wall.tzinfo is None or not start_wall<end:raise RehearsalError('slot expired or clock invalid')
    deadline=min(start_tick+duration_cap,start_tick+(end-start_wall).total_seconds())
    acquired=False;isolated=False;attempted=False;handback_ok=False;restored=False
    failure=None;samples=0;last_sample=None;termination='DURATION_LIMIT'
    def log(event,details=None): record({'event':event,'detail':details or {},'simulation_only':True,'modbus_writes':0})
    def check(now):
        current=qualify(now)
        if any(current.get(k)!=plan.get(k) for k in PINNED):
            raise RehearsalError('qualification changed or stale')
        if current.get('dispatch_enabled') is not False:raise RehearsalError('dispatch boundary changed')
    try:
        if not lock.acquire_nonblocking():raise RehearsalError('lock occupied')
        acquired=True;log('LOCK_ACQUIRED')
        if panel.is_active() is not True:raise RehearsalError('authority panel unavailable')
        panel.stop();isolated=True
        if panel.is_active() is not False:raise RehearsalError('authority isolation unverified')
        log('AUTHORITY_ISOLATED')
        check(utcnow())
        attempted=True # even an uncertain first command demands handback
        actuator.start(plan['action'],plan['rated_kw']);log('SIMULATED_START')
        while True:
            now=utcnow();tick=clock()
            if now.tzinfo is None or abs((now-start_wall).total_seconds()-(tick-start_tick))>max_skew:
                raise RehearsalError('wall/monotonic clock discontinuity')
            if now>=end: termination='SLOT_EXPIRED';break
            if tick>=deadline:break
            check(now)
            row=sample()
            if row.get('valid') is not True:raise RehearsalError('invalid telemetry')
            stamp=rc13_gateway.timestamp(row['observed_utc'])
            age=(now-stamp).total_seconds()
            if not -max_skew<=age<=max_gap:raise RehearsalError('stale telemetry')
            values=[float(row[k]) for k in ('soc_pct','battery_kw','grid_kw','reserve_pct')]
            if not all(math.isfinite(x) for x in values) or not 0<=values[0]<=100:raise RehearsalError('invalid sample values')
            soc,battery,grid,reserve=values
            if plan['action']=='GRID_CHARGE' and soc>=95:raise RehearsalError('charge SOC ceiling')
            if plan['action']=='EXPORT' and soc<reserve+reserve_margin:raise RehearsalError('export reserve floor')
            if last_sample is not None and tick-last_sample>max_gap:raise RehearsalError('telemetry sample gap')
            last_sample=tick;samples+=1
            log('SAMPLE',{'soc_pct':soc,'battery_kw':battery,'grid_kw':grid,
                          'energy_boundary':'BATTERY_PORT_AND_AGGREGATE_GRID_ONLY',
                          'grid_side_battery_delivery_verified':False})
            remaining=min(deadline-clock(),(end-utcnow()).total_seconds())
            if remaining>0:sleep(min(interval,remaining))
        log('SIMULATED_STOP',{'reason':termination,'samples':samples})
    except BaseException as exc:
        failure=exc
        try:log('ABORT',{'error':repr(exc)})
        except BaseException:pass
    finally:
        if attempted:
            try:handback_ok=(actuator.handback() is True)
            except BaseException as exc:
                try:log('HANDBACK_EXCEPTION',{'error':repr(exc)})
                except BaseException:pass
            try:log('HANDBACK_VERIFIED' if handback_ok else 'CRITICAL_HANDBACK_UNVERIFIED')
            except BaseException:handback_ok=False
        if isolated and (not attempted or handback_ok):
            try:panel.start();restored=(panel.is_active() is True)
            except BaseException:restored=False
            try:log('PANEL_RESTORED' if restored else 'CRITICAL_PANEL_NOT_RESTORED')
            except BaseException:restored=False
        if acquired:
            try:lock.release()
            except BaseException as exc:
                raise RehearsalError('critical lock release failure') from exc
    if attempted and not handback_ok:raise RehearsalError('CRITICAL: handback unverified; panel restart withheld')
    if isolated and not restored:raise RehearsalError('CRITICAL: panel restoration unverified')
    if failure:raise RehearsalError('rehearsal aborted: '+str(failure)) from failure
    if samples<2:raise RehearsalError('insufficient in-session evidence')
    return {'status':'SIMULATED_COMPLETE','termination':termination,'samples':samples,
            'handback_verified':handback_ok,'panel_restored':restored,
            'grid_side_battery_delivery_verified':False,'modbus_writes':0}

def main():
    print('BLOCKED: RC12 requires injected simulation adapters; LIVE MODBUS_WRITES=0')
    return 2
if __name__=='__main__':raise SystemExit(main())
