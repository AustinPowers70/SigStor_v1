#!/usr/bin/env python3
"""RC27 attended commissioning orchestration, no new Modbus actuation API.

On --execute only, with a local interactive challenge, delegate to the
already-commissioned 30s controller while independently tracing FC04 power.
Installation and --check never issue inverter writes. No scheduled invoker.

The underlying legacy controller owns live writes and handback; this wrapper
cannot guarantee recovery during full Thor/Proxmox/network failure.  A valid
aggregate-grid trace is not proof of battery-attributable grid-side energy.
"""
import argparse, datetime as dt, json, os, pathlib, subprocess, sys, threading, time, uuid
from commissioning_preflight_rc18 import inspect
from power_acquisition_rc9 import sample_once, append
from recovery_latch_rc21 import RecoveryLatch, RecoveryRequired
from supervised_export import qualify_export
from controller import qualify,systemctl,AUTH_UNIT

HERE=pathlib.Path(__file__).resolve().parent
DATA=pathlib.Path('/opt/sigenstor/data/rtm')
SCHEMA='SIGEN_PHASE3B_RC27_ATTENDED_PILOT_CORRELATION'
ACTIONS={'GRID_CHARGE':'--execute-30s-charge','EXPORT':'--execute-30s-export'}

class CommissioningHold(RuntimeError): pass

def eligibility(action):
    if action not in ACTIONS:raise CommissioningHold('unknown action')
    if action=='GRID_CHARGE':qualified,reserve=qualify()
    else:qualified,reserve=qualify_export(qualify)
    if qualified.get('AuthorityManualReady') is not True:raise CommissioningHold('MANUAL authority not ready')
    if qualified.get('Decision')!=action:raise CommissioningHold('RC13 action mismatch')
    before=inspect()
    if before['plant_handback_verified'] is not True:raise CommissioningHold('plant not in handback state')
    soc=before['soc_pct']
    if action=='GRID_CHARGE' and soc>=95:raise CommissioningHold('charge SOC limit')
    if action=='EXPORT' and soc<=reserve+2:raise CommissioningHold('export reserve margin')
    panel=systemctl('is-active',AUTH_UNIT)
    if panel.returncode!=0 or panel.stdout.strip()!='active':raise CommissioningHold('authority panel not running')
    return {'action':action,'source_slot':qualified.get('StartUtc'), 'reserve_percent':reserve,'before':before,
            'research_only':True,'autonomous_dispatch':False,'operator_live_authorised':False}

def local_consent(action,input_fn=input,is_tty=None):
    if is_tty is None:is_tty=sys.stdin.isatty()
    if is_tty is not True:raise CommissioningHold('local interactive TTY required')
    expected='AUTHORISE '+action+' 30 SECONDS'
    print('LIVE PLANT TEST. The existing commissioned controller may issue 500W charge or 650W export commands.')
    print('Thor/network loss during a pulse may prevent automatic handback. Monitor MySigen and retain manual plant control.')
    print('Type exactly: '+expected,flush=True)
    if input_fn('Approval: ')!=expected:raise CommissioningHold('operator did not authorise this specific pulse')
    return True

class Observation:
    def __init__(self,path,read=sample_once,writer=append,clock=time.monotonic,sleep=time.sleep):
        self.path=path;self.read=read;self.writer=writer;self.clock=clock;self.sleep=sleep
        self.stop=threading.Event();self.phase='BEFORE';self.counts={'BEFORE':0,'DURING':0,'AFTER':0};self.invalid=0;self.error=None
    def run(self):
        try:
            while not self.stop.is_set():
                tick=self.clock();row={'schema':SCHEMA,'record_type':'PLANT_SAMPLE',
                  'timestamp_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'phase':self.phase,
                  'valid':False,'modbus_writes_by_observer':0,'battery_grid_side_delivery_verified':False}
                try:
                    v=self.read()
                    if not isinstance(v,dict):raise ValueError('invalid sample')
                    import math
                    for k in ('soc_pct','battery_kw','grid_kw','home_kw','pv_kw'):
                        val=v[k]
                        if isinstance(val,bool) or not isinstance(val,(int,float)) or not math.isfinite(val):raise ValueError('nonfinite telemetry')
                        row[k]=float(val)
                    if not 0<=row['soc_pct']<=100:raise ValueError('invalid SOC')
                    row['valid']=True;self.counts[self.phase]+=1
                except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
                    row['error']=type(exc).__name__+': '+str(exc);self.invalid+=1
                self.writer(self.path,row)
                self.stop.wait(max(0,2-(self.clock()-tick)))
        except BaseException as exc:self.error=type(exc).__name__+': '+str(exc)
    def event(self,name,**detail):
        self.writer(self.path,{'schema':SCHEMA,'record_type':'SESSION_EVENT','event':name,
          'timestamp_utc':dt.datetime.now(dt.timezone.utc).isoformat(),**detail})

def orchestrate(action,approval=False,*,check=eligibility,consent=local_consent,
                popen=subprocess.Popen,observer_factory=Observation,preflight=inspect,
                latch_factory=RecoveryLatch,clock=time.monotonic,sleep=time.sleep,
                panel_check=None,trace_path=None,latch_path=None,delegate=None):
    """Execution only on explicit operator-approved interactive call.

    Live controller is the sole writer. Audit correlation records BEFORE/DURING/
    AFTER, but command onset is not claimed identical to child launch time.
    """
    ready=check(action)
    if approval is not True:raise CommissioningHold('execute requires --operator-ack')
    consent(action)
    # Eligibility may change while operator reads prompt; revalidate before latch.
    again=check(action)
    if ready['source_slot']!=again['source_slot'] or ready['reserve_percent']!=again['reserve_percent']:
        raise CommissioningHold('qualification changed during operator consent')
    session=uuid.uuid4().hex
    trace_path=pathlib.Path(trace_path or DATA/f'rc27-pilot-{session}.jsonl')
    latch_path=pathlib.Path(latch_path or DATA/'rc27-active-recovery-required.json')
    latch=latch_factory(latch_path)
    observer=observer_factory(trace_path)
    started=False;child=None;timeout=False;child_exit=None;after=None;panel_ok=False
    latch.arm(session) # persistent marker before any external controller action
    observer.event('SESSION_LATCH_ARMED',session_id=session,action=action,slot=again['source_slot'])
    t=threading.Thread(target=observer.run,name='rc27-fc04-observer',daemon=True)
    t.start()
    try:
        sleep(6)
        if observer.error or observer.counts['BEFORE']<2:raise CommissioningHold('baseline observer not healthy')
        # The legacy commissioned controller retains RC13 qualifications, writer
        # lock, panel isolation, live SOC guards and its own handback finally.
        cmd=[sys.executable,'-B',str(HERE/'controller.py'),ACTIONS[action],'--operator-ack'] if delegate is None else delegate(action)
        observer.phase='DURING'
        observer.event('DELEGATE_STARTED',session_id=session,command=ACTIONS[action])
        if delegate is None:
            child=popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        else:
            cmd,opts=cmd
            try:
                child=popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,**{k:v for k,v in opts.items() if k!='parent_close_fd'})
            finally:
                if 'parent_close_fd' in opts:os.close(opts['parent_close_fd'])
        started=True
        try:output,_=child.communicate(timeout=85);child_exit=child.returncode
        except subprocess.TimeoutExpired:
            timeout=True
            observer.event('CRITICAL_DELEGATE_TIMEOUT',session_id=session)
            # Avoid SIGKILL; it bypasses Python finally/handback.
            # If escalation is needed it must be operator-controlled.
            child.send_signal(__import__('signal').SIGINT)
            try:output,_=child.communicate(timeout=15);child_exit=child.returncode
            except subprocess.TimeoutExpired:
                output='CRITICAL: child still running; physical plant inspection required'
        observer.event('DELEGATE_EXIT',session_id=session,returncode=child_exit,output=output[-4000:])
        observer.phase='AFTER'
        sleep(8)
        if child_exit==0 and not timeout:
            after=preflight()
            pc=panel_check or (lambda:systemctl('is-active',AUTH_UNIT))
            p=pc();panel_ok=p.returncode==0 and p.stdout.strip()=='active'
            observer.event('POST_HAND_BACK',session_id=session,plant_ok=after['plant_handback_verified'],panel_ok=panel_ok)
    finally:
        observer.stop.set();t.join(timeout=6)
    pass_evidence=(child_exit==0 and not timeout and observer.error is None and observer.invalid==0
       and observer.counts['BEFORE']>=2 and observer.counts['DURING']>=5 and observer.counts['AFTER']>=2
       and isinstance(after,dict) and after.get('plant_handback_verified') is True and panel_ok)
    if pass_evidence:
        latch.clear_after_verified_completion(session,True)
    result={'schema':SCHEMA,'session_id':session,'action':action,'status':'SUPERVISED_PILOT_HANDBACK_CONFIRMED' if pass_evidence else 'HOLD_RECOVERY_REQUIRED',
        'live_controller_exit':child_exit,'controller_invoked':started,'delegate_timeout':timeout,
        'coverage':observer.counts,'invalid_samples':observer.invalid,'observer_error':observer.error,
        'plant_handback_verified':bool(after and after.get('plant_handback_verified')),
        'panel_restored':panel_ok,'recovery_latch_retained':not pass_evidence,
        'physical_delivery_verified':False,'host_loss_recovery_verified':False,'autonomous_dispatch':False,
        'trace_file':str(trace_path),'modbus_writes_by_observer':0}
    observer.event('SESSION_RESULT',**result)
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description='Operator-attended RC27 commissioning correlation; no autonomous operation')
    p.add_argument('--check',choices=tuple(ACTIONS))
    p.add_argument('--execute',choices=tuple(ACTIONS))
    p.add_argument('--operator-ack',action='store_true')
    args=p.parse_args(argv)
    try:
        if args.check:
            print(json.dumps({'schema':SCHEMA,'status':'READONLY_ELIGIBLE','evidence':eligibility(args.check),'modbus_writes':0},sort_keys=True))
            return 0
        if not args.execute:
            print('RC27_INSTALLED: --check performs read-only inspection. Live --execute requires interactive per-session approval; no automatic dispatch.');return 0
        result=orchestrate(args.execute,args.operator_ack)
        print(json.dumps(result,sort_keys=True))
        return 0 if result['status']=='SUPERVISED_PILOT_HANDBACK_CONFIRMED' else 2
    except (Exception,KeyboardInterrupt) as exc:
        print('RC27_FAIL_CLOSED',type(exc).__name__,str(exc),'PHYSICAL PLANT STATE MUST BE VERIFIED',file=sys.stderr)
        return 2
if __name__=='__main__':raise SystemExit(main())
