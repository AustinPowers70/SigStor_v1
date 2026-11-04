#!/usr/bin/env python3
"""Read-only commissioning interface inventory and explicit hard execution block."""
import argparse,json,sys
from pathlib import Path
import rc5_preflight

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--execute-slot',action='store_true')
    a=p.parse_args(argv)
    if a.execute_slot:
        print('BLOCKED: operator-commissioning live interface NOT released; MODBUS_WRITES=0')
        return 2
    rc=rc5_preflight.main([])
    print(json.dumps({'schema':'SIGEN_PHASE3B_RC14_ACTUATOR_INTERFACE',
                      'live_execution_enabled':False,'modbus_writes':0,
                      'control_contract':'500W_CHARGE_OR_650W_EXPORT_ONLY',
                      'handback_contract':'PCS_ZERO_MODE_2_REMOTE_EMS_OFF',
                      'rc13_readonly_preflight_exit':rc},sort_keys=True))
    return 0 if rc==0 else 2
if __name__=='__main__':sys.exit(main())
