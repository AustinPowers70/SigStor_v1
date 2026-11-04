from pathlib import Path
import shutil,hashlib,zipfile,subprocess,sys,textwrap
R=Path('/mnt/data'); src=R/'work_rc27/SigenStor_Phase3B_RC27'; out=R/'work_rc28/SigenStor_Phase3B_RC28'
if out.parent.exists(): shutil.rmtree(out.parent)
shutil.copytree(src,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
c=out/'controller'; tests=out/'tests'
# Preserve normal RC13 qualified paths; alter only injectable function boundaries.
p=c/'controller.py'; s=p.read_text(); s=s.replace('def execute(seconds=30,sleep=time.sleep,clock=time.monotonic,plant_cls=Modbus,release=handback):','def execute(seconds=30,sleep=time.sleep,clock=time.monotonic,plant_cls=Modbus,release=handback,qualification=None):')
start=s.index('def execute('); end=s.index('\ndef main():',start)
chunk=s[start:end].replace('    if seconds != 30:', '    qualification = qualification or (lambda stage: qualify())\n    if seconds != 30:').replace('action,reserve=qualify()','action,reserve=qualification("PRE")').replace('action2,reserve2=qualify()','action2,reserve2=qualification("ISOLATED")').replace('                qualify()','                qualification("ISOLATED")').replace('latest,current_reserve=qualify()','latest,current_reserve=qualification("ACTIVE")')
s=s[:start]+chunk+s[end:];p.write_text(s)
p=c/'supervised_export.py';s=p.read_text().replace('handback=export_handback, sleep=time.sleep,clock=time.monotonic):','handback=export_handback, sleep=time.sleep,clock=time.monotonic,qualification=None):')
start=s.index('def perform_export(');end=s.index('\ndef qualify_export(',start)
chunk=s[start:end].replace('    with lock.open', '    eligibility = qualification or (lambda stage: qualify_export(qualify))\n    with lock.open').replace('qualify_export(qualify)','eligibility()')
# Fix closure replacement also affected lambda assignment
chunk=chunk.replace('eligibility = qualification or (lambda stage: eligibility())','eligibility = qualification or (lambda stage: qualify_export(qualify))')
chunk=chunk.replace('action,reserve=eligibility()','action,reserve=eligibility("PRE")').replace('newer,newreserve=eligibility()','newer,newreserve=eligibility("ISOLATED")').replace('latest,current=eligibility()','latest,current=eligibility("ISOLATED")').replace('current_action,current_reserve=eligibility()','current_action,current_reserve=eligibility("ACTIVE")')
s=s[:start]+chunk+s[end:];p.write_text(s)
(c/'commissioning_permit_rc28.py').write_text('''#!/usr/bin/env python3
"""Manual commissioning-only qualification, WITHOUT RC13 economic-slot permission.

This is NOT trading authorisation and cannot run alone. Mandatory plant, reserve,
manual authority and panel checks happen here and again in the commissioned
actuator. No Modbus writes in this module.
"""
import json,math,stat
from pathlib import Path
from commissioning_preflight_rc18 import inspect
from controller import AUTH_UNIT,systemctl
from rc13_gateway import AUTH,SET

class PermitHold(RuntimeError):pass

def safe_json(p):
    p=Path(p)
    if p.is_symlink() or not p.is_file() or not stat.S_ISREG(p.stat().st_mode):
        raise PermitHold('missing/unsafe input: '+str(p))
    return json.loads(p.read_text())

def qualify(action,stage='PRE',*,authority_path=AUTH,reserve_path=SET,preflight=inspect,panel=systemctl):
    if action not in ('GRID_CHARGE','EXPORT'):raise PermitHold('unknown commissioning action')
    authority=safe_json(authority_path); settings=safe_json(reserve_path)
    reserve=settings.get('SoftReservePercent')
    if type(reserve) is not int or reserve not in range(0,96,5):raise PermitHold('invalid soft reserve')
    if (authority.get('requested')!='MANUAL' or authority.get('dispatch_authorised') is not False
         or authority.get('remote_ems_verified_off') is not True):
        raise PermitHold('MANUAL authority not exclusive or not acknowledged')
    if stage not in ('PRE','ISOLATED','ACTIVE'):raise PermitHold('invalid phase')
    if stage=='PRE':
        check=preflight()
        if check.get('plant_handback_verified') is not True:raise PermitHold('physical handback not verified')
        soc=check.get('soc_pct')
        if type(soc) not in (float,int) or not math.isfinite(soc) or not 0<=soc<=100:raise PermitHold('invalid SOC')
        if action=='GRID_CHARGE' and not reserve<=soc<95:raise PermitHold('charge SOC outside bounds')
        if action=='EXPORT' and not reserve+2<=soc<=98:raise PermitHold('export SOC outside bounds')
        service=panel('is-active',AUTH_UNIT)
        if service.returncode or service.stdout.strip()!='active':raise PermitHold('authority panel unhealthy')
    return {'Decision':action,'StartUtc':'MANUAL_COMMISSIONING_30S','AuthorityManualReady':True,
            'CommissioningOnly':True,'DispatchAuthorised':False,'ModbusWrites':0},reserve
''')
(c/'commissioning_controller_rc28.py').write_text('''#!/usr/bin/env python3
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
''')
# existing RC27 telemetry orchestrator reuse; alternate qualification and delegate through narrowly extended parameters.
p=c/'attended_commissioning_rc27.py';s=p.read_text()
s=s.replace('panel_check=None,trace_path=None,latch_path=None):','panel_check=None,trace_path=None,latch_path=None,delegate=None):')
s=s.replace("cmd=[sys.executable,'-B',str(HERE/'controller.py'),ACTIONS[action],'--operator-ack']", "cmd=[sys.executable,'-B',str(HERE/'controller.py'),ACTIONS[action],'--operator-ack'] if delegate is None else delegate(action)")
# delegate() yields (cmd, extra_popen_opts); existing tests still use default list
s=s.replace("child=popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)","""if delegate is None:
            child=popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        else:
            cmd,opts=cmd
            child=popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,**opts)""")
p.write_text(s)
(c/'attended_commissioning_rc28.py').write_text('''#!/usr/bin/env python3
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
      'env':{**os.environ,'SIGEN_RC28_AUTH_FD':str(r)},'pass_fds':(r,)}

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
''')
# Correct pipe lifecycle by non inheritable parent close after Popen, via callback cleanup hook.
p=c/'attended_commissioning_rc27.py';s=p.read_text();s=s.replace("child=popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,**opts)", """try:
                child=popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,**{k:v for k,v in opts.items() if k!='parent_close_fd'})
            finally:
                if 'parent_close_fd' in opts:os.close(opts['parent_close_fd'])""");p.write_text(s)
p=c/'attended_commissioning_rc28.py';s=p.read_text().replace("'pass_fds':(r,)}", "'pass_fds':(r,), 'parent_close_fd':r}");p.write_text(s)
# Very important: session eligibility is re-checked inside real actuator; race stops under lock.
(tests/'test_rc28.py').write_text('''import sys,unittest,tempfile,json,types,inspect
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'controller'))
import commissioning_permit_rc28 as permit
import attended_commissioning_rc28 as parent
import commissioning_controller_rc28 as child
import controller,supervised_export
class RC28(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();p=Path(self.temp.name)
  self.a=p/'authority.json';self.s=p/'reserve.json';self.s.write_text(json.dumps({'SoftReservePercent':20}))
  self.a.write_text(json.dumps({'requested':'MANUAL','dispatch_authorised':False,'remote_ems_verified_off':True}))
  self.pf=lambda:{'plant_handback_verified':True,'soc_pct':60}
  self.panel=lambda *args:types.SimpleNamespace(returncode=0,stdout='active')
 def tearDown(self):self.temp.cleanup()
 def q(self,action):return permit.qualify(action,authority_path=self.a,reserve_path=self.s,preflight=self.pf,panel=self.panel)
 def test_manual_charge_no_rc13_required(self):
  q,reserve=self.q('GRID_CHARGE');self.assertTrue(q['CommissioningOnly']);self.assertEqual(reserve,20)
 def test_manual_export(self):self.assertEqual(self.q('EXPORT')[0]['Decision'],'EXPORT')
 def test_dispatch_authority_rejected(self):
  self.a.write_text(json.dumps({'requested':'MANUAL','dispatch_authorised':True,'remote_ems_verified_off':True}))
  with self.assertRaises(permit.PermitHold):self.q('GRID_CHARGE')
 def test_remote_ems_authority_rejected(self):
  self.a.write_text(json.dumps({'requested':'MANUAL','dispatch_authorised':False,'remote_ems_verified_off':False}))
  with self.assertRaises(permit.PermitHold):self.q('GRID_CHARGE')
 def test_reserve_rejected(self):
  self.s.write_text(json.dumps({'SoftReservePercent':105}))
  with self.assertRaises(permit.PermitHold):self.q('GRID_CHARGE')
 def test_plant_not_handed_back(self):
  self.pf=lambda:{'plant_handback_verified':False,'soc_pct':60}
  with self.assertRaises(permit.PermitHold):self.q('GRID_CHARGE')
 def test_charge_soc_guard(self):
  self.pf=lambda:{'plant_handback_verified':True,'soc_pct':96}
  with self.assertRaises(permit.PermitHold):self.q('GRID_CHARGE')
 def test_export_soc_guard(self):
  self.pf=lambda:{'plant_handback_verified':True,'soc_pct':21}
  with self.assertRaises(permit.PermitHold):self.q('EXPORT')
 def test_no_direct_dispatch_without_approval(self):
  with self.assertRaisesRegex(Exception,'operator-ack'):
   from attended_commissioning_rc27 import orchestrate
   orchestrate('GRID_CHARGE',False,check=lambda a:{'source_slot':'MANUAL_COMMISSIONING_30S','reserve_percent':20})
 def test_active_phase_avoids_handback_during_live_pulse(self):
  self.pf=lambda:(_ for _ in ()).throw(RuntimeError('preflight must not run while active'))
  q,_=permit.qualify('GRID_CHARGE','ACTIVE',authority_path=self.a,reserve_path=self.s,preflight=self.pf,panel=self.panel)
  self.assertEqual(q['Decision'],'GRID_CHARGE')
 def test_existing_rc13_qualify_default_unchanged(self):
  self.assertEqual(inspect.signature(controller.execute).parameters['qualification'].default,None)
  self.assertEqual(inspect.signature(supervised_export.perform_export).parameters['qualification'].default,None)
 def test_no_40034(self):
  for f in ('commissioning_controller_rc28.py','commissioning_permit_rc28.py','attended_commissioning_rc28.py'):
   txt=(Path(__file__).resolve().parent.parent/'controller'/f).read_text()
   self.assertNotIn('write(40034',txt);self.assertNotIn('write_u32(40034',txt)
''')
(out/'COMMISSIONING_RC28.md').write_text('''# RC28 — commissioning-only permit (operator-attended, no economic slot required)

The existing RC13 economic qualification is **unchanged** for tariff/trading operation. RC28 adds a separate manual 30-second physical commissioning qualification that uses MANUAL authority, verified Remote EMS off, self-consumption/PCS zero, SOC and reserve guards, authority-panel health and durable recovery latch, with explicit local TTY confirmation. It reuses the commissioned 500W charge and 650W export routines and RC27 event/2s power capture. It requires **no current RC13 economic slot**.

## Non-actuating preflight

    python3 -B /opt/sigenstor/scripts/phase3b-supervised-rc28/controller/attended_commissioning_rc28.py --check GRID_CHARGE

## Live commissioning

NOT authorised by installation or by these instructions. Do not run without explicit operator decision, MySigen monitoring, manual recovery capability and acceptance of the host-loss handback exposure. If separately approved, command is `--execute GRID_CHARGE --operator-ack` with local action-specific TTY phrase. No timers/service changes. A successful 30-second pulse is not full-slot acceptance.

## Restrictions

- Charge 500 W for 30 seconds; export 650 W for 30 seconds; no 40034.
- Local Modbus writer lock and temporary authority-panel isolation; safety latch is armed before delegation.
- Normal controller `qualify()` and export `qualify_export()` are unchanged by default.
- If the operator/Thor/network disappears during actuation, guaranteed handback is **not** established.
- No autonomous dispatch, no overnight schedule modification, no long-duration control.
- Legacy controller bypass is still possible and requires consolidation before a production system.
''')
(out/'RELEASE_NOTES_RC28.md').write_text('''# RC28 - manual commissioning-only pilot eligibility
- RC27 failed at HOLD_OUTSIDE_HORIZON even when an operator wanted a bounded physical test. RC28 removes economic-slot precondition **only for commissioning**.
- RC13 optimiser and all normal tariff qualification remain unchanged.
- Existing Modbus control sequences are reused via injected qualification functions, with original default qualification retained.
- Installation remains nonactuating; 12 targeted tests. Requires explicit local operator live approval for each pilot.
- Does not address Thor host/network loss, no full-slot or unattended permission.
''')
(out/'install.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
sha256sum -c SHA256SUMS
python3 -B -m unittest discover -s tests -p 'test_rc28.py' -q
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc28
if [[ -e "$TARGET" ]]; then echo 'RC28 already present: refusing overwrite';exit 2;fi
mkdir -p "$TARGET"
cp -a controller accepted tests *.md SHA256SUMS "$TARGET"/
echo 'RC28 staged; manual commissioning-only preflight available. No services or Modbus writes.'
''')
(out/'rollback.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
echo 'RC28 does not modify services. Revert to RC27 by using previous path; do not delete any recovery-required latch without physical investigation.'
''')
for n in ('install.sh','rollback.sh'):(out/n).chmod(0o755)
sha=[]
for f in sorted(out.rglob('*')):
 if f.is_file() and f.name!='SHA256SUMS':sha.append(f'{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.relative_to(out)}')
(out/'SHA256SUMS').write_text('\n'.join(sha)+'\n')
z=R/'SigenStor_Phase3B_RC28_Manual_Commissioning.zip'
with zipfile.ZipFile(z,'w',compression=zipfile.ZIP_DEFLATED) as archive:
 for f in sorted(out.rglob('*')):
  if f.is_file():archive.write(f,arcname=str(f.relative_to(out.parent)))
print('PACKAGE',z,'SIZE',z.stat().st_size)
p=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(tests),'-p','test_rc28.py','-q'],cwd=out,capture_output=True,text=True)
print(p.stdout,p.stderr,'EXIT',p.returncode)
if p.returncode:raise SystemExit(1)
with zipfile.ZipFile(z) as arc:print('ZIP',arc.testzip())
