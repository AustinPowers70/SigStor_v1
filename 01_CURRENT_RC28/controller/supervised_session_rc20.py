#!/usr/bin/env python3
"""RC20 operator-supervised bounded session integration.

NO public live entrypoint. The only shipped invoker is a blocked CLI. This
injectable core can use a real adapter *only after* a separate independently
qualified recovery interlock and explicit operator session authorization are
commissioned. RC13 decisions are never authorization. Not a recovery mechanism.
"""
import datetime as dt
import math
import time
from dataclasses import dataclass

from actuator_contract_rc14 import PlantSequence, LIMITS
from commissioning_transport_rc16 import RestrictedPlant

class SessionHold(RuntimeError): pass
class CriticalHandback(SessionHold): pass

@dataclass(frozen=True)
class SessionAuthorization:
    session_id: str
    action: str
    slot_end_utc: dt.datetime
    operator_acknowledged: bool
    recovery_verified: bool
    qualification_current: bool
    manual_authority: bool
    reserve_percent: float
    source_fingerprint: str
    # This status must be supplied from separately commissioned proof, never RC13.

    def validate(self, now):
        if not self.session_id or not isinstance(self.session_id,str): raise SessionHold('invalid session ID')
        if self.action not in LIMITS: raise SessionHold('action not commissioned')
        if not isinstance(self.source_fingerprint,str) or len(self.source_fingerprint)!=64 or any(c not in '0123456789abcdef' for c in self.source_fingerprint):
            raise SessionHold('invalid pinned source fingerprint')
        if self.slot_end_utc.tzinfo is None or now.tzinfo is None or not now < self.slot_end_utc:
            raise SessionHold('invalid or expired slot')
        for value in (self.operator_acknowledged,self.recovery_verified,self.qualification_current,self.manual_authority):
            if type(value) is not bool or value is not True: raise SessionHold('operator/recovery/qualification gate not met')
        if not isinstance(self.reserve_percent,(float,int)) or not math.isfinite(self.reserve_percent) or not 10<=self.reserve_percent<=95:
            raise SessionHold('invalid reserve')


def run_injected(*, authorization, plant, lock, panel, qualify, sample, audit, recovery,
                 utcnow, monotonic, sleep, duration_limit=1800, sample_interval=2, max_gap=10):
    """Fail-closed orchestration. No connection is constructed or CLI supplied.

    audit(event,detail) must durably persist BEFORE accepting a write intention.
    recovery() must be an independently validated active-watchdog check and
    repeated each observation. An in-process claim alone does NOT qualify it.
    """
    if not callable(audit) or not callable(recovery):raise SessionHold('external audit/recovery required')
    if not (0<duration_limit<=1800 and 0<sample_interval<=5 and sample_interval<=max_gap<=30):
        raise SessionHold('invalid timing limits')
    now=utcnow();authorization.validate(now)
    if recovery() is not True: raise SessionHold('independent recovery unavailable')
    if not all(callable(getattr(x,m,None)) for x,m in ((lock,'acquire_nonblocking'),(lock,'release'),(panel,'is_active'),(panel,'stop'),(panel,'start'))):
        raise SessionHold('authority interface missing')
    for m in ('read_holding','call','write','write_u32','close'):
        if not callable(getattr(plant,m,None)):raise SessionHold('plant interface missing')
    # Never create/own a Modbus connection here: enclosing authorized operator
    # session owns lifecycle and guarantees independent supervision.
    acquired=isolated=attempted=handback_ok=restored=False
    failure=None; samples=0; last_tick=None; termination='DURATION_LIMIT'
    restricted=None
    def record(evt, details=None):audit(evt,{'session_id':authorization.session_id,**(details or {})})
    def assert_qualified():
        if recovery() is not True:raise SessionHold('recovery liveness lost')
        q=qualify(utcnow())
        if not isinstance(q,dict) or q.get('valid') is not True or q.get('action')!=authorization.action or q.get('slot_end_utc')!=authorization.slot_end_utc or q.get('source_fingerprint')!=authorization.source_fingerprint:
            raise SessionHold('qualification changed or stale')
    try:
        if not lock.acquire_nonblocking():raise SessionHold('writer lock held')
        acquired=True;record('LOCK_ACQUIRED')
        if panel.is_active() is not True:raise SessionHold('panel not active before isolation')
        panel.stop();isolated=True
        if panel.is_active() is not False:raise SessionHold('panel isolation failed')
        record('PANEL_ISOLATED')
        assert_qualified()
        restricted=RestrictedPlant(plant,lambda event,detail:record(event,detail))
        seq=PlantSequence(restricted)
        start_wall=utcnow();start_tick=monotonic()
        deadline=min(start_tick+duration_limit,start_tick+(authorization.slot_end_utc-start_wall).total_seconds())
        attempted=True
        record('START_ATTEMPT',{'action':authorization.action,'watts':LIMITS[authorization.action]})
        seq.start(authorization.action,LIMITS[authorization.action]);record('START_ACK')
        while True:
            wall=utcnow();tick=monotonic()
            if wall.tzinfo is None or abs((wall-start_wall).total_seconds()-(tick-start_tick))>5:raise SessionHold('clock drift')
            if wall>=authorization.slot_end_utc:termination='SLOT_EXPIRED';break
            if tick>=deadline:break
            assert_qualified()
            row=sample()
            if not isinstance(row,dict) or row.get('valid') is not True:raise SessionHold('invalid telemetry')
            values=[row.get(k) for k in ('soc_pct','battery_kw','grid_kw')]
            if any(type(x) not in (float,int) or not math.isfinite(x) for x in values):raise SessionHold('nonfinite telemetry')
            stamp=row.get('observed_utc')
            if not isinstance(stamp,dt.datetime) or stamp.tzinfo is None or not -3<=(wall-stamp).total_seconds()<=max_gap:
                raise SessionHold('sample timestamp stale or invalid')
            soc=values[0]
            if not 0<=soc<=100:raise SessionHold('invalid SOC')
            if authorization.action=='GRID_CHARGE' and soc>=95:raise SessionHold('SOC ceiling')
            if authorization.action=='EXPORT' and soc<=authorization.reserve_percent:raise SessionHold('SOC reserve')
            if last_tick is not None and tick-last_tick>max_gap:raise SessionHold('sample gap')
            last_tick=tick;samples+=1
            record('SAMPLE',{'soc_pct':soc,'battery_kw':values[1],'grid_kw':values[2],
                             'boundary':'BATTERY_PORT_AND_AGGREGATE_GRID_NOT_INDEPENDENT_DELIVERY'})
            delay=min(sample_interval,deadline-monotonic(),(authorization.slot_end_utc-utcnow()).total_seconds())
            if delay>0:sleep(delay)
        record('SESSION_END',{'reason':termination,'samples':samples})
    except BaseException as exc:
        failure=exc
        try:record('ABORT',{'error':type(exc).__name__+': '+str(exc)})
        except BaseException:pass
    finally:
        if attempted:
            try:
                handback_ok=seq.handback() is True
            except BaseException:handback_ok=False
            try:record('HANDBACK_VERIFIED' if handback_ok else 'CRITICAL_HANDBACK_UNVERIFIED')
            except BaseException:handback_ok=False
        if restricted is not None:
            try:restricted.close()
            except BaseException:handback_ok=False
        if isolated and (not attempted or handback_ok):
            try:
                panel.start();restored=panel.is_active() is True
            except BaseException:restored=False
            try:record('PANEL_RESTORED' if restored else 'CRITICAL_PANEL_NOT_RESTORED')
            except BaseException:restored=False
        if acquired:
            try:lock.release()
            except BaseException as exc:raise CriticalHandback('lock release failed') from exc
    if attempted and not handback_ok:raise CriticalHandback('handback unverified; panel restart withheld')
    if isolated and not restored:raise CriticalHandback('panel restore unverified')
    if failure:raise SessionHold('aborted: '+str(failure)) from failure
    if samples<2:raise SessionHold('insufficient measurement evidence')
    return {'state':'SUPERVISED_SESSION_COMPLETED','samples':samples,'handback_verified':True,
            'grid_side_battery_delivery_verified':False,'automatic_dispatch':False}


def main():
    print('RC20_STAGED_ONLY: NO OPERATOR LIVE ENTRYPOINT; MODBUS_WRITES=0')
    return 2
if __name__=='__main__':raise SystemExit(main())
