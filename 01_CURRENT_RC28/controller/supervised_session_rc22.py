#!/usr/bin/env python3
"""RC22 non-live guarded session wrapper with RC22 evidence latch."""
from recovery_attestation_rc22 import AttestedRecoveryLatch, RecoveryRequired
from supervised_session_rc20 import run_injected, SessionHold

def run_guarded(*, latch_path, **kwargs):
    auth=kwargs.get('authorization')
    if auth is None:raise SessionHold('authorization missing')
    latch=AttestedRecoveryLatch(latch_path)
    latch.arm(auth.session_id)
    result=run_injected(**kwargs)
    if result.get('handback_verified') is not True:raise RecoveryRequired('handback unverified')
    latch.clear_after_verified_completion(auth.session_id, True)
    return result

def main():
    print('RC22_STAGED_ONLY: INDEPENDENT_RECOVERY_NOT_COMMISSIONED; MODBUS_WRITES=0')
    return 2
if __name__=='__main__':raise SystemExit(main())
