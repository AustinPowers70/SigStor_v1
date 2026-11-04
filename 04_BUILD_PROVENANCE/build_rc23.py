from pathlib import Path
import zipfile, shutil, subprocess, hashlib
base=Path('/mnt/data'); work=base/'work_rc23'; root=work/'SigenStor_Phase3B_RC23'
if work.exists():shutil.rmtree(work)
work.mkdir()
with zipfile.ZipFile(base/'SigenStor_Phase3B_RC22_Recovery_Attestation_OfflineTested.zip') as z:
 for info in z.infolist():
  parts=Path(info.filename).parts
  if not parts or parts[0]!='SigenStor_Phase3B_RC22' or '__pycache__' in parts or info.filename.endswith('.pyc'):continue
  dest=root.joinpath(*parts[1:])
  if info.is_dir():dest.mkdir(parents=True,exist_ok=True);continue
  dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(info))
(root/'controller'/'attended_pilot_rc23.py').write_text('''#!/usr/bin/env python3
"""RC23 attended short-pulse commissioning core; injection-only, NO LIVE CLI.

This path is deliberately separate from RC20 full-slot recovery protocol. It
models an operator-attended 30s test of previously commissioned 500W/650W
commands, but cannot establish safety during total loss of Thor. There is no
production invoker or user-controllable adapter binding.
"""
import datetime as dt
import math
from dataclasses import dataclass
from actuator_contract_rc14 import LIMITS, PlantSequence
from commissioning_transport_rc16 import RestrictedPlant
from recovery_attestation_rc22 import AttestedRecoveryLatch

class PilotHold(RuntimeError): pass
class PilotCritical(PilotHold): pass

@dataclass(frozen=True)
class PilotPermit:
    session_id: str
    action: str
    expires_utc: dt.datetime
    operator_approved: bool
    manual_authority: bool
    plant_handback_verified: bool
    reserve_percent: float
    # No RC13 trading horizon is required for a controlled engineering pulse.

    def validate(self, now):
        if type(self.session_id) is not str or not 1<=len(self.session_id)<=128:raise PilotHold('invalid session ID')
        if self.action not in LIMITS:raise PilotHold('action outside commissioned pilot setpoints')
        if self.operator_approved is not True or self.manual_authority is not True or self.plant_handback_verified is not True:
            raise PilotHold('manual commissioning authority missing')
        if not isinstance(now,dt.datetime) or now.tzinfo is None or not isinstance(self.expires_utc,dt.datetime) or self.expires_utc.tzinfo is None:
            raise PilotHold('timezone-aware expiry required')
        remaining=(self.expires_utc-now).total_seconds()
        if not 0<remaining<=60:raise PilotHold('permit expiry must be within 60 seconds')
        if type(self.reserve_percent) not in (int,float) or not math.isfinite(self.reserve_percent) or not 10<=self.reserve_percent<=95:
            raise PilotHold('invalid reserve')


def run_injected(*,permit,plant,lock,panel,latch_path,presence,qualify,sample,audit,
                 utcnow,monotonic,sleep,duration=30,interval=2,max_gap=6):
    """Always fail closed; exclusive and supervised; only fake adapters in tests.

    presence() is external physical/operator presence; DOES NOT establish
    independent system recovery and cannot justify unattended/full-slot use.
    The prevalidated permit is NOT a persisted authority or live CLI.
    """
    if type(duration) not in (int,float) or duration!=30 or type(interval) not in (int,float) or not 0<interval<=2 or not interval<=max_gap<=6:
        raise PilotHold('only bounded 30-second commissioning pilot supported')
    now=utcnow();permit.validate(now)
    if not all(callable(x) for x in (presence,qualify,sample,audit,utcnow,monotonic,sleep)):
        raise PilotHold('required injected interface missing')
    if not all(callable(getattr(lock,m,None)) for m in ('acquire_nonblocking','release')) or not all(callable(getattr(panel,m,None)) for m in ('is_active','stop','start')):
        raise PilotHold('authority isolation unavailable')
    if not all(callable(getattr(plant,m,None)) for m in ('read_holding','call','write','write_u32','close')):
        raise PilotHold('plant contract unavailable')
    if presence() is not True:raise PilotHold('operator not present')
    if qualify(permit,now) is not True:raise PilotHold('pilot qualification failed')
    latch=AttestedRecoveryLatch(latch_path)
    acquired=isolated=attempted=handback_ok=restored=False
    samples=0;last_tick=None;failure=None;seq=None;restricted=None
    def record(name,**detail):
        audit(name,{'session_id':permit.session_id,**detail})
    try:
        if not lock.acquire_nonblocking():raise PilotHold('writer lock not acquired')
        acquired=True
        if panel.is_active() is not True:raise PilotHold('authority panel baseline missing')
        panel.stop();isolated=True
        if panel.is_active() is not False:raise PilotHold('authority panel isolation failed')
        # Persist a fail-closed interlock BEFORE any live-capable write attempt.
        latch.arm(permit.session_id)
        record('PILOT_LATCH_ARMED')
        restricted=RestrictedPlant(plant,lambda event,detail:record(event,**detail))
        seq=PlantSequence(restricted)
        start=monotonic();deadline=start+duration
        if presence() is not True or qualify(permit,utcnow()) is not True:raise PilotHold('pre-start approval withdrawn')
        attempted=True
        record('PILOT_START_ATTEMPT',action=permit.action,watts=LIMITS[permit.action])
        seq.start(permit.action,LIMITS[permit.action])
        record('PILOT_START_ACK')
        while monotonic()<deadline:
            wall=utcnow();tick=monotonic()
            if wall>=permit.expires_utc:raise PilotHold('permit expired')
            if tick-start>duration+1:raise PilotHold('duration exceeded')
            if presence() is not True:raise PilotHold('operator presence lost')
            if qualify(permit,wall) is not True:raise PilotHold('qualification withdrawn')
            row=sample()
            if not isinstance(row,dict) or row.get('valid') is not True:raise PilotHold('telemetry unavailable')
            observed=row.get('observed_utc')
            if not isinstance(observed,dt.datetime) or observed.tzinfo is None or not -3<=(wall-observed).total_seconds()<=max_gap:
                raise PilotHold('telemetry stale')
            vals=[row.get(k) for k in ('soc_pct','battery_kw','grid_kw')]
            if any(type(v) not in (float,int) or not math.isfinite(v) for v in vals):raise PilotHold('nonfinite telemetry')
            soc=vals[0]
            if not 0<=soc<=100:raise PilotHold('SOC impossible')
            if permit.action=='GRID_CHARGE' and soc>=95:raise PilotHold('charge ceiling')
            if permit.action=='EXPORT' and soc<=permit.reserve_percent:raise PilotHold('export reserve')
            if last_tick is not None and tick-last_tick>max_gap:raise PilotHold('sample gap')
            last_tick=tick;samples+=1
            record('PILOT_SAMPLE',soc_pct=soc,battery_kw=vals[1],grid_kw=vals[2])
            delay=min(interval,deadline-monotonic(),(permit.expires_utc-utcnow()).total_seconds())
            if delay>0:sleep(delay)
        record('PILOT_DURATION_END',samples=samples)
    except BaseException as exc:
        failure=exc
        try:record('PILOT_ABORT',reason=type(exc).__name__+': '+str(exc))
        except BaseException:pass
    finally:
        if attempted:
            try:handback_ok=seq.handback() is True
            except BaseException:handback_ok=False
            try:record('PILOT_HANDBACK_VERIFIED' if handback_ok else 'PILOT_CRITICAL_HANDBACK_UNVERIFIED')
            except BaseException:handback_ok=False
        if restricted is not None:
            try:restricted.close()
            except BaseException:handback_ok=False
        if isolated and (not attempted or handback_ok):
            try:panel.start();restored=panel.is_active() is True
            except BaseException:restored=False
            try:record('PILOT_PANEL_RESTORED' if restored else 'PILOT_CRITICAL_PANEL_RESTORE')
            except BaseException:restored=False
        # The OS lock is process-scoped; durable latch remains on uncertainty.
        if acquired:
            try:lock.release()
            except BaseException as exc:raise PilotCritical('writer lock release failed') from exc
    # If an interruption occurs between arming and safe restoration, latch is retained.
    if attempted and not handback_ok:raise PilotCritical('handback unverified; recovery latch retained')
    if isolated and not restored:raise PilotCritical('authority panel restore unverified; latch retained')
    if failure is not None:raise PilotHold('pilot aborted: '+str(failure)) from failure
    if samples<2:raise PilotHold('insufficient telemetry evidence; latch retained')
    if not attempted:raise PilotHold('pilot was not started')
    latch.clear_after_verified_completion(permit.session_id,True)
    return {'schema':'SIGEN_PHASE3B_RC23_ATTENDED_PILOT','status':'SIMULATED_PILOT_COMPLETE',
            'samples':samples,'handback_verified':True,'automatic_dispatch':False,
            'grid_side_battery_delivery_verified':False,'host_loss_recovery_verified':False}

def main():
    print('RC23_INJECTION_ONLY: NO LIVE OPERATOR CLI; MODBUS_WRITES=0')
    return 2
if __name__=='__main__':raise SystemExit(main())
''')
(root/'tests'/'test_rc23.py').write_text('''import unittest,sys,tempfile,pathlib,datetime as dt
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'controller'))
from attended_pilot_rc23 import PilotPermit,PilotHold,PilotCritical,run_injected,main
from recovery_attestation_rc22 import AttestedRecoveryLatch,RecoveryRequired
import test_rc20

class SimClock:
 def __init__(self):self.n=0;self.wall=dt.datetime(2026,11,4,19,0,tzinfo=dt.timezone.utc)
 def monotonic(self):return self.n
 def utcnow(self):return self.wall+dt.timedelta(seconds=self.n)
 def sleep(self,n):self.n+=n
class Lock:
 def __init__(self,allow=True):self.allow=allow;self.held=False
 def acquire_nonblocking(self):self.held=self.allow;return self.held
 def release(self):self.held=False
class Panel:
 def __init__(self):self.active=True
 def is_active(self):return self.active
 def stop(self):self.active=False
 def start(self):self.active=True
class Plant:
 def __init__(self):self.register={40029:0,40031:2,40032:0,40001:0};self.writes=[];self.closed=False;self.fail_handback=False
 def read_holding(self,k):return self.register[k]
 def call(self,fc,payload):
  if self.fail_handback:return b'\\x04\\x00\\x00\\x00\\x01'
  return b'\\x04'+self.register[40001].to_bytes(4,'big')
 def write(self,k,v):self.writes.append((k,v));self.register[k]=v
 def write_u32(self,k,v):self.writes.append((k,v));self.register[k]=v
 def close(self):self.closed=True
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=pathlib.Path(self.tmp.name)/'latch';self.clock=SimClock()
  self.plant=Plant();self.lock=Lock();self.panel=Panel();self.events=[];self.present=lambda:True;self.qual=lambda p,t:True
  self.permit=PilotPermit('operator-rc23','GRID_CHARGE',self.clock.utcnow()+dt.timedelta(seconds=50),True,True,True,20.)
 def tearDown(self):self.tmp.cleanup()
 def runpilot(self,**overrides):
  args=dict(permit=self.permit,plant=self.plant,lock=self.lock,panel=self.panel,latch_path=self.path,
       presence=self.present,qualify=self.qual,sample=lambda:{'valid':True,'observed_utc':self.clock.utcnow(),
       'soc_pct':50.,'battery_kw':-0.5,'grid_kw':0.6},
       audit=lambda e,d:self.events.append((e,d)),utcnow=self.clock.utcnow,
       monotonic=self.clock.monotonic,sleep=self.clock.sleep)
  args.update(overrides);return run_injected(**args)
 def test_simulated_charge(self):
  x=self.runpilot();self.assertEqual(x['samples'],15);self.assertFalse(self.path.exists());self.assertTrue(self.panel.active)
  self.assertEqual(self.plant.register[40029],0);self.assertEqual(self.plant.register[40031],2)
 def test_simulated_export(self):
  self.permit=PilotPermit('operator-rc23','EXPORT',self.clock.utcnow()+dt.timedelta(seconds=50),True,True,True,20.)
  self.runpilot();self.assertIn((40001,650),self.plant.writes);self.assertEqual(self.plant.register[40001],0)
 def test_no_reserved_register_write(self):
  self.runpilot();self.assertFalse(any(k==40034 for k,v in self.plant.writes))
 def test_no_unbounded_duration(self):
  with self.assertRaises(PilotHold):self.runpilot(duration=120)
  self.assertFalse(self.plant.writes)
 def test_missing_operator_ack(self):
  self.permit=PilotPermit('operator-rc23','EXPORT',self.clock.utcnow()+dt.timedelta(seconds=50),False,True,True,20.)
  with self.assertRaises(PilotHold):self.runpilot()
  self.assertFalse(self.plant.writes)
 def test_expired_permit(self):
  self.permit=PilotPermit('operator-rc23','EXPORT',self.clock.utcnow()-dt.timedelta(seconds=1),True,True,True,20.)
  with self.assertRaises(PilotHold):self.runpilot()
 def test_lock_denied(self):
  self.lock.allow=False
  with self.assertRaises(PilotHold):self.runpilot()
  self.assertFalse(self.plant.writes)
 def test_preflight_qualification_denied(self):
  with self.assertRaises(PilotHold):self.runpilot(qualify=lambda p,t:False)
  self.assertFalse(self.plant.writes)
 def test_preflight_presence_denied(self):
  with self.assertRaises(PilotHold):self.runpilot(presence=lambda:False)
  self.assertFalse(self.plant.writes)
 def test_presence_loss_handback(self):
  with self.assertRaises(PilotHold):self.runpilot(presence=lambda:self.clock.n<6)
  self.assertEqual(self.plant.register[40029],0);self.assertTrue(self.panel.active)
 def test_soc_ceiling(self):
  with self.assertRaises(PilotHold):self.runpilot(sample=lambda:{'valid':True,'observed_utc':self.clock.utcnow(),'soc_pct':95.,'battery_kw':0.,'grid_kw':0.})
  self.assertEqual(self.plant.register[40029],0)
 def test_reserve(self):
  self.permit=PilotPermit('operator-rc23','EXPORT',self.clock.utcnow()+dt.timedelta(seconds=50),True,True,True,20.)
  with self.assertRaises(PilotHold):self.runpilot(sample=lambda:{'valid':True,'observed_utc':self.clock.utcnow(),'soc_pct':20.,'battery_kw':0.,'grid_kw':0.})
 def test_unverified_handback_retains_latch(self):
  self.plant.fail_handback=True
  with self.assertRaises(PilotCritical):self.runpilot()
  self.assertTrue(self.path.exists());self.assertFalse(self.panel.active)
 def test_marker_blocks_second_pilot(self):
  AttestedRecoveryLatch(self.path).arm('unrecovered')
  with self.assertRaises(PilotHold):self.runpilot()
  self.assertFalse(self.plant.writes)
 def test_no_live_cli(self):self.assertEqual(main(),2)
 def test_false_claims(self):
  r=self.runpilot();self.assertFalse(r['grid_side_battery_delivery_verified']);self.assertFalse(r['host_loss_recovery_verified'])
 def test_no_unattended_synthetic_expiry(self):
  with self.assertRaises(PilotHold):self.runpilot(presence=lambda:None)
 def test_stale_sample(self):
  with self.assertRaises(PilotHold):self.runpilot(sample=lambda:{'valid':True,'observed_utc':self.clock.utcnow()-dt.timedelta(seconds=20),'soc_pct':50.,'battery_kw':0.,'grid_kw':0.})
 def test_qualification_lost(self):
  with self.assertRaises(PilotHold):self.runpilot(qualify=lambda p,t:self.clock.n<8)
  self.assertEqual(self.plant.register[40029],0)
 def test_audit_before_start(self):
  self.runpilot();names=[e for e,_ in self.events];self.assertLess(names.index('PILOT_LATCH_ARMED'),names.index('PILOT_START_ATTEMPT'))
''')
(root/'RELEASE_NOTES.md').write_text('''# SigenStor Phase 3B RC23 — Thor-only operator-attended pulse integration

**No live operator command exists in this release.** RC23 is a Python-injected testable integration core for the previously commissioned **30-second** charge/export pilot setpoints (500 W/650 W). The full-slot RC22 path is retained but blocked; no autonomous dispatch. RC13 economic optimiser remains frozen.

The user elected not to deploy a second independent Linux supervisor. RC23 therefore **does not claim host-loss recovery**. It separates brief, physically operator-attended *commissioning research* from full-duration operation and forbids promoting a simulated predicate to physical proof.

RC23 adds: strictly 30-second bounded sessions; short-expiry manual permit; repeated operator-presence and qualification probes; exclusive-writer lock; isolation of authority panel; persistent latch BEFORE first write attempt; 2-second telemetry sampling with stale/SOC/reserve guards; verified readback handback; retained latch and panel isolation on ambiguous handback; explicit grid-side attribution caveat. All actions are injectable test adapters: there is no publicly invokable Modbus dispatch path, service change, timer, permission change or scheduled write.

**Unresolved acceptance:** No direct real plant binding, no proven recovery from total Thor/NAS/network loss, no full-slot physical energy direction confirmation. A 30-second test on a real plant requires separate explicit operator approval and a live commissioning release. Operator presence alone cannot stop a persistent power command after loss of Thor. Register 40034 must never be touched.
''')
(root/'THOR_ONLY_COMMISSIONING.md').write_text('''# Thor-only commissioning decision — 4 November 2026

## Chosen scope
No independent Linux recovery supervisor is to be installed. The separate prototype is retired from the active workstream. Keep RC22 as rollback and RC23 as candidate for short physically supervised commissioning tests. This changes *scope*, not the physics of uncontrolled network or host loss.

## Commissioning sequence (not yet performed)
1. Operator checks physical plant and MySigen and explicitly authorises one 30-second pulse. Confirm operator has an independent way to end Remote EMS if Thor disappears; otherwise keep actuation disabled.
2. Ensure 40029=0, 40031=2, 40001=0, only one writer, exclusive manual authority, valid SOC/soft reserve, no charge above 95%; ensure 40034 unchanged.
3. Run one limited, monitored trial with sustained observations at about two seconds and a durable audit; freeze further trials after any uncertain handback.
4. Confirm PCS=0, mode=2, Remote EMS=0, correlate actual battery/grid observations; do not claim aggregate grid indicates battery-attributable energy.
5. Only after acceptance decide whether longer than 30-second runs are tolerable under the host-loss risk. Full-slot sessions remain blocked without a risk resolution specifically accepted by the operator.

## Important boundary
The RC23 Python engine is INJECTION ONLY and cannot physically actuate the inverter from an installed CLI. There is no new approval prompt needed for read-only engineering, but live writes require explicit approval.
''')
(root/'install.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
sha256sum -c SHA256SUMS
python3 -B -W ignore::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -q
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc23
if [[ -e "$TARGET" ]]; then echo 'RC23 already installed; refusing overwrite'; exit 2; fi
mkdir -p "$TARGET"
cp -a controller accepted tests RELEASE_NOTES.md RECOVERY_DESIGN.md INDEPENDENT_RECOVERY_ACCEPTANCE.md THOR_ONLY_COMMISSIONING.md SHA256SUMS "$TARGET"/
echo 'RC23 staged: THOR-ONLY ATTENDED PILOT CORE, INJECTION-ONLY; no services or Modbus writes.'
''')
(root/'rollback.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc23
[[ -d "$TARGET" ]] || exit 0
rm -rf -- "$TARGET"
echo 'RC23 removed; durable operational latches, if any, retained.'
''')
for p in (root/'install.sh',root/'rollback.sh'):p.chmod(0o755)
manifest=[]
for p in sorted(root.rglob('*')):
 if p.is_file() and p.name!='SHA256SUMS' and '__pycache__' not in p.parts:
  manifest.append(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(root).as_posix())
(root/'SHA256SUMS').write_text('\n'.join(manifest)+'\n')
r=subprocess.run(['python3','-B','-W','ignore::ResourceWarning','-m','unittest','discover','-s','tests','-p','test_*.py','-q'],cwd=root,capture_output=True,text=True)
(base/'rc23_test.log').write_text(r.stdout+r.stderr)
print('result:',r.returncode, r.stderr[-1400:])
if r.returncode:raise SystemExit(1)
out=base/'SigenStor_Phase3B_RC23_Attended_Pilot_OfflineTested.zip'
with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
 for p in sorted(root.rglob('*')):
  if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':z.write(p,p.relative_to(work))
with zipfile.ZipFile(out) as z: assert z.testzip() is None
print(out, out.stat().st_size)
