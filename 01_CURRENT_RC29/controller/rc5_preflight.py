#!/usr/bin/env python3
"""RC5 standalone read-only preflight and explicit blocked execute entrypoint."""
import argparse, datetime as dt, json, sys
from pathlib import Path
import rc13_gateway as gateway
import integrated_preview
import session_integration_rc5 as integration

def main(argv=None):
    p=argparse.ArgumentParser(description='RC5 no-dispatch read-only preflight')
    p.add_argument('--candidate',type=Path,default=gateway.DOC)
    p.add_argument('--settings',type=Path,default=gateway.SET)
    p.add_argument('--authority',type=Path,default=gateway.AUTH)
    p.add_argument('--r5',type=Path,default=integrated_preview.DEFAULT_R5)
    p.add_argument('--execute-slot',action='store_true')
    a=p.parse_args(argv)
    if a.execute_slot:
        print('BLOCKED: RC5 production full-slot actuation not commissioned; MODBUS_WRITES=0')
        return 2
    try:
        documents=[integrated_preview.read(path) for path in (a.candidate,a.settings,a.authority,a.r5)]
        out=integration.prepare(*documents,dt.datetime.now(dt.timezone.utc))
        print(json.dumps(out,sort_keys=True,indent=2,allow_nan=False));return 0
    except Exception as exc:
        print('PHASE3B_RC5_FAIL_CLOSED',type(exc).__name__,str(exc),'MODBUS_WRITES=0');return 2
if __name__=='__main__':sys.exit(main())
