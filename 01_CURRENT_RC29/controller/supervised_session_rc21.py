#!/usr/bin/env python3
"""RC21 guarded session adapter. Staged offline; no live entrypoint."""
from recovery_latch_rc21 import RecoveryLatch,RecoveryRequired
from supervised_session_rc20 import run_injected,SessionHold

def run_guarded(*,latch_path,**kwargs):
    auth=kwargs.get('authorization')
    if auth is None:raise SessionHold('authorization missing')
    latch=RecoveryLatch(latch_path)
    latch.arm(auth.session_id)
    # Do not clear after abort/exception: conservative until operator recovery review.
    result=run_injected(**kwargs)
    if result.get('handback_verified') is not True:raise RecoveryRequired('handback not verified')
    latch.clear_after_verified_completion(auth.session_id,True)
    return result

def main():
    print('RC21_STAGED_ONLY: NO OPERATOR LIVE ENTRYPOINT; MODBUS_WRITES=0')
    return 2
if __name__=='__main__':raise SystemExit(main())
