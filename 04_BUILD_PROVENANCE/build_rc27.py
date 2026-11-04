from pathlib import Path
import shutil, textwrap, hashlib, zipfile, subprocess, sys
root=Path('/mnt/data'); src=root/'work_rc26/SigenStor_Phase3B_RC26'; staging=root/'work_rc27'; dst=staging/'SigenStor_Phase3B_RC27'
if staging.exists():shutil.rmtree(staging)
shutil.copytree(src,dst,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
code=r'''#!/usr/bin/env python3
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
                panel_check=None,trace_path=None,latch_path=None):
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
        cmd=[sys.executable,'-B',str(HERE/'controller.py'),ACTIONS[action],'--operator-ack']
        observer.phase='DURING'
        observer.event('DELEGATE_STARTED',session_id=session,command=ACTIONS[action])
        child=popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
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
'''
(dst/'controller/attended_commissioning_rc27.py').write_text(code)
(dst/'COMMISSIONING_RC27.md').write_text('''# RC27 attended physical commissioning coordinator

**Operator-approved live writes possible only when running `--execute ACTION --operator-ack` and typing the exact action-specific approval locally.** Installation and `--check` perform no writes.

`--execute` delegates to the previously commissioned 30-second `controller.py` charge/export implementation. It does not add a new Modbus command sequence or enable timers. It requires an active valid RC13 action and MANUAL authority, prior handback, correct SOC, and the authority panel running. The existing legacy controller still performs the actual qualification and writes; its command path was previously commissioned at 500 W charging and 650 W PCS export. Never write 40034.

A durable RC27 recovery latch is armed before the child controller starts and is cleared only after the child exits successfully, real read-only postflight proves Remote EMS off/self-consumption/PCS-zero, the panel is active, and valid observation samples exist before, during, and after. Otherwise latch remains and needs supervised physical recovery review. **A recovery latch cannot restore control after physical host loss.** The earlier controller uses its own writer lock; RC27 does not override it. Legacy controller invocation outside RC27 is not blocked by this latch.

Telemetry phases are relative to the delegated controller's process lifetime, not a readback of the actual instant of Modbus actuation. Aggregate grid energy is not battery-attributable. Measured power and pilot event correlation require human commissioning review.

**Preflight (no writes):**

    python3 -B /opt/sigenstor/scripts/phase3b-supervised-rc27/controller/attended_commissioning_rc27.py --check GRID_CHARGE

Use `EXPORT` to check the export pilot. If no RC13 qualified slot exists, the result is a normal HOLD.

**Live pilot only during attended and specifically authorised physical commissioning:**

    python3 -B /opt/sigenstor/scripts/phase3b-supervised-rc27/controller/attended_commissioning_rc27.py --execute GRID_CHARGE --operator-ack

The command presents a TTY-specific confirmation phrase, samples read-only FC04 data during the pilot, and delegates the command to the previously commissioned operator-only controller. This is not permitted without an operator present, a recoverable plant, and explicit approval of residual Thor/network-loss risk. Stop at 30-second pilots; never use for 30-minute full-slot dispatch.

Physical recovery of an uncertain latch requires operator engineering assessment. No software bypass is supplied. Existing legacy code can still run separately; production consolidation must eliminate legacy bypass paths before wider deployment.
''')
(dst/'RELEASE_NOTES_RC27.md').write_text('''# RC27 — Attended physical-pilot correlation

- Adds real-world operator-gated orchestration around the existing commissioned controller; no new register writes/values.
- Captures physical FC04 telemetry pre/during/post action with a durable recovery latch.
- Fails closed on any uncertain controller exit, telemetry integrity, panel restoration or physical handback.
- Explicit local TTY consent required for each potential live actuation.
- Does not solve Thor/LXC/network loss recovery and does not authorise unattended/full-slot dispatch.
- RC26 read-only capture, RC25 evidence tools and RC13 optimiser unchanged.
''')
# targeted tests deliberately inject callables; do not connect to real plant.
test=r'''import sys,unittest,datetime as dt,types
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'controller'))
import attended_commissioning_rc27 as m

class TestRC27(unittest.TestCase):
 def test_readonly_no_approval(self):
  with self.assertRaisesRegex(m.CommissioningHold,'operator-ack'):
   m.orchestrate('GRID_CHARGE',False,check=lambda a:{'source_slot':'x','reserve_percent':20})
 def test_consent_no_tty(self):
  with self.assertRaisesRegex(m.CommissioningHold,'TTY'):
   m.local_consent('EXPORT',is_tty=False)
 def test_consent_exact(self):
  with self.assertRaisesRegex(m.CommissioningHold,'did not authorise'):
   m.local_consent('GRID_CHARGE',input_fn=lambda _: 'yes',is_tty=True)
  self.assertTrue(m.local_consent('EXPORT',input_fn=lambda _: 'AUTHORISE EXPORT 30 SECONDS',is_tty=True))
 def test_action_allowlist(self):
  self.assertEqual(set(m.ACTIONS),{'GRID_CHARGE','EXPORT'})
 def test_observation_record(self):
  rows=[]
  obs=m.Observation('/simulated',read=lambda:{'soc_pct':60,'battery_kw':-1,'grid_kw':0,'pv_kw':0,'home_kw':1},writer=lambda p,r:rows.append(r))
  obs.stop=types.SimpleNamespace(is_set=lambda:len(rows)>=1,wait=lambda n:None)
  obs.run()
  self.assertEqual(obs.counts['BEFORE'],1)
  self.assertTrue(rows[0]['valid'])
  self.assertEqual(rows[0]['modbus_writes_by_observer'],0)
 def test_observation_bad(self):
  rows=[]
  obs=m.Observation('/simulated',read=lambda:{'soc_pct':float('nan'),'battery_kw':-1,'grid_kw':0,'pv_kw':0,'home_kw':1},writer=lambda p,r:rows.append(r))
  obs.stop=types.SimpleNamespace(is_set=lambda:len(rows)>=1,wait=lambda n:None)
  obs.run()
  self.assertEqual(obs.invalid,1)
 def test_check_invalid_action(self):
  with self.assertRaisesRegex(m.CommissioningHold,'unknown action'):
   m.eligibility('WRONG')
 def test_execution_aborts_on_qual_change_before_latch(self):
  calls=[]
  def check(a):
   calls.append(a);return {'source_slot':str(len(calls)),'reserve_percent':20}
  with self.assertRaisesRegex(m.CommissioningHold,'qualification changed'):
   m.orchestrate('GRID_CHARGE',True,check=check,consent=lambda a:True,latch_factory=lambda p:self.fail('latch should not be touched'))
'''
(dst/'tests/test_rc27.py').write_text(test)
# replace installer with targeted tests and verified checksum staging only
installer='''#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
sha256sum -c SHA256SUMS
python3 -B -m unittest discover -s tests -p 'test_rc27.py' -q
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc27
if [[ -e "$TARGET" ]]; then echo 'RC27 already present; refusing overwrite'; exit 2; fi
mkdir -p "$TARGET"
cp -a controller accepted tests *.md SHA256SUMS "$TARGET"/
echo 'RC27 staged: live pilot path INVOCATION REQUIRES operator-specific TTY consent. Installer makes no Modbus writes or service changes.'
'''
(dst/'install.sh').write_text(installer)
(dst/'install.sh').chmod(0o755)
(dst/'rollback.sh').write_text('#!/usr/bin/env bash\nset -euo pipefail\necho "RC27 rollback: stop using RC27 commissioning CLI; RC26 remains installed. No service alterations."\n')
(dst/'rollback.sh').chmod(0o755)
# Remove stale SHA256 file before regenerating
(dst/'SHA256SUMS').unlink(missing_ok=True)
files=sorted(f for f in dst.rglob('*') if f.is_file() and f.name!='SHA256SUMS')
(dst/'SHA256SUMS').write_text(''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+str(f.relative_to(dst))+'\n' for f in files))
log=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests','-p','test_rc27.py','-q'],cwd=dst,capture_output=True,text=True)
print(log.stdout,log.stderr,log.returncode)
if log.returncode:raise SystemExit('tests failed')
archive=root/'SigenStor_Phase3B_RC27_Attended_Commissioning.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
 for f in sorted(dst.rglob('*')):
  if f.is_file():z.write(f,arcname=str(f.relative_to(staging)))
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
print('ZIP',archive,archive.stat().st_size)
