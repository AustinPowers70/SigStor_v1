#!/usr/bin/env python3
"""RC23 attended short-pulse commissioning core; injection-only, NO LIVE CLI.

This path is deliberately separate from RC20 full-slot recovery protocol. It
models an operator-attended 30s test of previously commissioned 500W/650W
commands, but cannot establish safety during total loss of Thor. There is no
production invoker or user-controllable adapter binding.
"""
import datetime as dt
import math
from dataclasses import dataclass
from actuator_contract_rc14 import LIMITS, PlantSequence
from commissioning_transport_rc16 import RestrictedPlant
from recovery_attestation_rc22 import AttestedRecoveryLatch

class PilotHold(RuntimeError): pass
class PilotCritical(PilotHold): pass

@dataclass(frozen=True)
class PilotPermit:
    session_id: str
    action: str
    expires_utc: dt.datetime
    operator_approved: bool
    manual_authority: bool
    plant_handback_verified: bool
    reserve_percent: float
    # No RC13 trading horizon is required for a controlled engineering pulse.

    def validate(self, now):
        if type(self.session_id) is not str or not 1<=len(self.session_id)<=128:raise PilotHold('invalid session ID')
        if self.action not in LIMITS:raise PilotHold('action outside commissioned pilot setpoints')
        if self.operator_approved is not True or self.manual_authority is not True or self.plant_handback_verified is not True:
            raise PilotHold('manual commissioning authority missing')
        if not isinstance(now,dt.datetime) or now.tzinfo is None or not isinstance(self.expires_utc,dt.datetime) or self.expires_utc.tzinfo is None:
            raise PilotHold('timezone-aware expiry required')
        remaining=(self.expires_utc-now).total_seconds()
        if not 0<remaining<=60:raise PilotHold('permit expiry must be within 60 seconds')
        if type(self.reserve_percent) not in (int,float) or not math.isfinite(self.reserve_percent) or not 10<=self.reserve_percent<=95:
            raise PilotHold('invalid reserve')


def run_injected(*,permit,plant,lock,panel,latch_path,presence,qualify,sample,audit,
                 utcnow,monotonic,sleep,duration=30,interval=2,max_gap=6):
    """Always fail closed; exclusive and supervised; only fake adapters in tests.

    presence() is external physical/operator presence; DOES NOT establish
    independent system recovery and cannot justify unattended/full-slot use.
    The prevalidated permit is NOT a persisted authority or live CLI.
    """
    if type(duration) not in (int,float) or duration!=30 or type(interval) not in (int,float) or not 0<interval<=2 or not interval<=max_gap<=6:
        raise PilotHold('only bounded 30-second commissioning pilot supported')
    # This is an INJECTION-ONLY rehearsal runner. Mere method compatibility
    # must never let an actual Modbus adapter through this test interface.
    if getattr(plant,'simulation_only',None) is not True:
        raise PilotHold('RC25 simulation boundary: real plant not accepted')
    now=utcnow();permit.validate(now)
    if not all(callable(x) for x in (presence,qualify,sample,audit,utcnow,monotonic,sleep)):
        raise PilotHold('required injected interface missing')
    if not all(callable(getattr(lock,m,None)) for m in ('acquire_nonblocking','release')) or not all(callable(getattr(panel,m,None)) for m in ('is_active','stop','start')):
        raise PilotHold('authority isolation unavailable')
    if not all(callable(getattr(plant,m,None)) for m in ('read_holding','call','write','write_u32','close')):
        raise PilotHold('plant contract unavailable')
    if presence() is not True:raise PilotHold('operator not present')
    if qualify(permit,now) is not True:raise PilotHold('pilot qualification failed')
    latch=AttestedRecoveryLatch(latch_path)
    acquired=isolated=attempted=handback_ok=restored=False
    samples=0;last_tick=None;failure=None;seq=None;restricted=None
    def record(name,**detail):
        audit(name,{'session_id':permit.session_id,**detail})
    try:
        if not lock.acquire_nonblocking():raise PilotHold('writer lock not acquired')
        acquired=True
        if panel.is_active() is not True:raise PilotHold('authority panel baseline missing')
        # Durable marker PRECEDES any change to control authority. Even a partial
        # panel-stop failure must not leave an unlatched unknown control state.
        latch.arm(permit.session_id)
        record('PILOT_LATCH_ARMED')
        isolated=True  # stop() can partially succeed and then raise
        record('PILOT_PANEL_STOP_ATTEMPT')
        panel.stop()
        if panel.is_active() is not False:raise PilotHold('authority panel isolation failed')
        restricted=RestrictedPlant(plant,lambda event,detail:record(event,**detail))
        seq=PlantSequence(restricted)
        start=monotonic();deadline=start+duration
        if presence() is not True or qualify(permit,utcnow()) is not True:raise PilotHold('pre-start approval withdrawn')
        attempted=True
        record('PILOT_START_ATTEMPT',action=permit.action,watts=LIMITS[permit.action])
        seq.start(permit.action,LIMITS[permit.action])
        record('PILOT_START_ACK')
        while monotonic()<deadline:
            wall=utcnow();tick=monotonic()
            if wall>=permit.expires_utc:raise PilotHold('permit expired')
            if tick-start>duration+1:raise PilotHold('duration exceeded')
            if presence() is not True:raise PilotHold('operator presence lost')
            if qualify(permit,wall) is not True:raise PilotHold('qualification withdrawn')
            row=sample()
            if not isinstance(row,dict) or row.get('valid') is not True:raise PilotHold('telemetry unavailable')
            observed=row.get('observed_utc')
            if not isinstance(observed,dt.datetime) or observed.tzinfo is None or not -3<=(wall-observed).total_seconds()<=max_gap:
                raise PilotHold('telemetry stale')
            vals=[row.get(k) for k in ('soc_pct','battery_kw','grid_kw')]
            if any(type(v) not in (float,int) or not math.isfinite(v) for v in vals):raise PilotHold('nonfinite telemetry')
            soc=vals[0]
            if not 0<=soc<=100:raise PilotHold('SOC impossible')
            if permit.action=='GRID_CHARGE' and soc>=95:raise PilotHold('charge ceiling')
            if permit.action=='EXPORT' and soc<=permit.reserve_percent:raise PilotHold('export reserve')
            if last_tick is not None and tick-last_tick>max_gap:raise PilotHold('sample gap')
            last_tick=tick;samples+=1
            record('PILOT_SAMPLE',soc_pct=soc,battery_kw=vals[1],grid_kw=vals[2])
            delay=min(interval,deadline-monotonic(),(permit.expires_utc-utcnow()).total_seconds())
            if delay>0:sleep(delay)
        record('PILOT_DURATION_END',samples=samples)
    except BaseException as exc:
        failure=exc
        try:record('PILOT_ABORT',reason=type(exc).__name__+': '+str(exc))
        except BaseException:pass
    finally:
        if attempted:
            try:handback_ok=seq.handback() is True
            except BaseException:handback_ok=False
            try:record('PILOT_HANDBACK_VERIFIED' if handback_ok else 'PILOT_CRITICAL_HANDBACK_UNVERIFIED')
            except BaseException:handback_ok=False
        if restricted is not None:
            try:restricted.close()
            except BaseException:handback_ok=False
        if isolated and (not attempted or handback_ok):
            try:panel.start();restored=panel.is_active() is True
            except BaseException:restored=False
            try:record('PILOT_PANEL_RESTORED' if restored else 'PILOT_CRITICAL_PANEL_RESTORE')
            except BaseException:restored=False
        # The OS lock is process-scoped; durable latch remains on uncertainty.
        if acquired:
            try:lock.release()
            except BaseException as exc:raise PilotCritical('writer lock release failed') from exc
    # If an interruption occurs between arming and safe restoration, latch is retained.
    if attempted and not handback_ok:raise PilotCritical('handback unverified; recovery latch retained')
    if isolated and not restored:raise PilotCritical('authority panel restore unverified; latch retained')
    if failure is not None:raise PilotHold('pilot aborted: '+str(failure)) from failure
    if samples<2:raise PilotHold('insufficient telemetry evidence; latch retained')
    if not attempted:raise PilotHold('pilot was not started')
    latch.clear_after_verified_completion(permit.session_id,True)
    return {'schema':'SIGEN_PHASE3B_RC23_ATTENDED_PILOT','status':'SIMULATED_PILOT_COMPLETE',
            'samples':samples,'handback_verified':True,'automatic_dispatch':False,
            'grid_side_battery_delivery_verified':False,'host_loss_recovery_verified':False}

def main():
    print('RC23_INJECTION_ONLY: NO LIVE OPERATOR CLI; MODBUS_WRITES=0')
    return 2
if __name__=='__main__':raise SystemExit(main())
