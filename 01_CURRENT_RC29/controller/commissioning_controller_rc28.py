#!/usr/bin/env python3
"""Commissioning-only child: fixed 30-second operator-approved pilot.

No schedule, timer or autonomous activation. Called by attended RC28 parent
and deliberately refuses direct command-line invocation.
"""
import os,sys
from controller import execute,qualify,systemctl,audit,LOCK,AUTH_UNIT,HOST
from supervised_export import perform_export
from commissioning_permit_rc28 import qualify as permitted

def run(action,permit_fn=permitted):
    if action not in ('GRID_CHARGE','EXPORT'):raise RuntimeError('unknown action')
    qualification=lambda phase:permit_fn(action,phase)
    audit('RC28_OPERATOR_COMMISSIONING_REQUEST',action)
    if action=='GRID_CHARGE':return execute(qualification=qualification)
    return perform_export(qualify=qualify,systemctl=systemctl,audit=audit,lock=LOCK,
        auth_unit=AUTH_UNIT,host=HOST,qualification=qualification)

if __name__=='__main__':
    # Parent passes an unpredictable per-session secret via inherited file
    # descriptor; no self-approval/direct CLI.  This is an accidental-use
    # guard, not an adversarial code-integrity or malicious-root boundary.
    if len(sys.argv)!=2 or sys.argv[1] not in ('GRID_CHARGE','EXPORT'):
        raise SystemExit('RC28_INTERNAL_CHILD_ONLY')
    fd=int(os.environ.get('SIGEN_RC28_AUTH_FD','-1'))
    if fd<3:raise SystemExit('RC28_INTERNAL_CHILD_ONLY')
    try: grant=os.read(fd,256).decode()
    except (OSError,UnicodeError):raise SystemExit('RC28_INTERNAL_CHILD_ONLY')
    if grant!='RC28:'+sys.argv[1]+':APPROVED':raise SystemExit('RC28_INTERNAL_CHILD_ONLY')
    try:run(sys.argv[1]);print('RC28_SUPERVISED_COMMISSIONING_HANDBACK_VERIFIED')
    except Exception as exc:
        print('RC28_COMMISSIONING_FAILED',repr(exc),flush=True);raise SystemExit(2)
