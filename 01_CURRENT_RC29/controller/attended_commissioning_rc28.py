#!/usr/bin/env python3
"""RC28 attended commissioning; no economic slot prerequisite, no automatic dispatch.

Installation and --check are read-only. Only --execute with a local operator
TTY confirmation can invoke the fixed 30-second previously commissioned pilot.
"""
import argparse,json,os,pathlib,sys
from commissioning_permit_rc28 import qualify,PermitHold
from attended_commissioning_rc27 import orchestrate,local_consent,CommissioningHold

HERE=pathlib.Path(__file__).resolve().parent

def check(action):
    q,reserve=qualify(action)
    return {'action':action,'source_slot':q['StartUtc'],'reserve_percent':reserve,
       'commissioning_only':True,'rc13_modified':False,'autonomous_dispatch':False,
       'operator_live_authorised':False,'modbus_writes':0}

def delegated(action):
    r,w=os.pipe()
    try:
        os.set_inheritable(r,True)
        os.write(w,('RC28:'+action+':APPROVED').encode())
    finally:os.close(w)
    # A single pipe FD is passed to the child. Close it in parent after Popen
    # requires wrapper callback; manage via post-launch close-on-parent hook.
    return [sys.executable,'-B',str(HERE/'commissioning_controller_rc28.py'),action],{
      'env':{**os.environ,'SIGEN_RC28_AUTH_FD':str(r)},'pass_fds':(r,), 'parent_close_fd':r}

def main(argv=None):
    p=argparse.ArgumentParser()
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--check',choices=('GRID_CHARGE','EXPORT'))
    group.add_argument('--execute',choices=('GRID_CHARGE','EXPORT'))
    p.add_argument('--operator-ack',action='store_true')
    a=p.parse_args(argv)
    try:
        if a.check:
            print(json.dumps({'schema':'SIGEN_PHASE3B_RC28_MANUAL_COMMISSIONING','status':'READONLY_ELIGIBLE',
                'evidence':check(a.check),'modbus_writes':0},sort_keys=True));return 0
        result=orchestrate(a.execute,a.operator_ack,check=check,consent=local_consent,
            delegate=delegated,latch_path='/opt/sigenstor/data/rtm/rc28-recovery-required.json')
        print(json.dumps(result,sort_keys=True));return 0 if result['status']=='SUPERVISED_PILOT_HANDBACK_CONFIRMED' else 2
    except (Exception,KeyboardInterrupt) as exc:
        print('RC28_FAIL_CLOSED',type(exc).__name__,str(exc),'PHYSICAL PLANT STATE MUST BE VERIFIED',file=sys.stderr)
        return 2
if __name__=='__main__':raise SystemExit(main())
