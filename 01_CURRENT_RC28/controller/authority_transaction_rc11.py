#!/usr/bin/env python3
"""RC11 simulation-only authority transaction. No network, systemctl or Modbus writes.

Rehearses single-writer, authority isolation and verified handback lifecycle.
Real actuators cannot pass the simulation_only gate. The preflight function must
be re-evaluated throughout the session by the bounded runner in a later release.
"""
import dataclasses

class AuthorityError(RuntimeError): pass

@dataclasses.dataclass(frozen=True)
class Result:
    state: str
    handback_verified: bool
    panel_restarted: bool
    start_attempted: bool
    error: str = ''


def rehearsal(*, plan, lock, panel, actuator, audit, qualify):
    if plan.get('state') != 'QUALIFIED_SIMULATION_ONLY' or plan.get('dispatch_enabled') is not False:
        raise AuthorityError('simulation-only qualified plan required')
    if not getattr(actuator, 'simulation_only', False) or not getattr(panel, 'simulation_only', False):
        raise AuthorityError('real actuator or authority panel prohibited')
    if not getattr(lock, 'simulation_only', False):
        raise AuthorityError('real lock adapter prohibited')
    acquired=False; isolated=False; started=False; handed_back=False; restarted=False; failure=None
    try:
        if not lock.acquire_nonblocking(): raise AuthorityError('single-writer lock occupied')
        acquired=True
        audit('LOCK_ACQUIRED', {})
        if not panel.is_active(): raise AuthorityError('authority panel not active')
        panel.stop(); isolated=True
        audit('PANEL_ISOLATED', {})
        if panel.is_active(): raise AuthorityError('authority panel isolation unverified')
        current=qualify()
        for key in ('state','action','start_utc','end_utc','source_fingerprint'):
            if current.get(key) != plan.get(key): raise AuthorityError('qualification changed: '+key)
        started=True # even first uncertain start must trigger handback
        actuator.start(plan['action'], plan['rated_kw'])
        audit('SIMULATED_START', {'action':plan['action']})
    except BaseException as exc:
        failure=exc
        audit('ABORT', {'error':str(exc)})
    finally:
        if started:
            try: handed_back=actuator.handback() is True
            except BaseException as exc:
                audit('HANDBACK_EXCEPTION', {'error':str(exc)})
            audit('HANDBACK_VERIFIED' if handed_back else 'CRITICAL_HANDBACK_UNVERIFIED', {})
        # Restore panel only if no plant-control attempt, or verified handback.
        if isolated and (not started or handed_back):
            try:
                panel.start()
                restarted=panel.is_active() is True
            except BaseException as exc:
                audit('PANEL_RESTART_EXCEPTION', {'error':str(exc)})
            audit('PANEL_RESTORED' if restarted else 'CRITICAL_PANEL_NOT_RESTORED', {})
        if acquired: lock.release()
    if started and not handed_back: raise AuthorityError('CRITICAL: simulated handback unverified; authority restart withheld')
    if isolated and not restarted: raise AuthorityError('CRITICAL: authority panel restart unverified')
    if failure: raise AuthorityError('rehearsal aborted: '+str(failure)) from failure
    return Result('SIMULATED_TRANSACTION_VERIFIED',handed_back,restarted,started)


def main():
    print('BLOCKED: RC11 is simulation-only; NO LIVE ACTUATOR; MODBUS_WRITES=0')
    return 2
if __name__=='__main__': raise SystemExit(main())
