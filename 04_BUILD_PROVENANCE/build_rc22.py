from pathlib import Path
import zipfile,shutil,subprocess,hashlib
base=Path('/mnt/data');work=base/'work_rc22';root=work/'SigenStor_Phase3B_RC22'
if work.exists():shutil.rmtree(work)
work.mkdir()
with zipfile.ZipFile(base/'SigenStor_Phase3B_RC21_Recovery_Latch_OfflineTested.zip') as z:
 for info in z.infolist():
  p=Path(info.filename)
  if not p.parts or p.parts[0]!='SigenStor_Phase3B_RC21' or '__pycache__' in p.parts or p.suffix=='.pyc':continue
  dest=root.joinpath(*p.parts[1:])
  if info.is_dir():dest.mkdir(parents=True,exist_ok=True);continue
  dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(info))
(root/'controller'/'recovery_attestation_rc22.py').write_text('''#!/usr/bin/env python3
"""RC22 recovery witness contract. No Modbus, service, or live execution APIs.

Attestation verification MUST be supplied by an independently deployed,
commissioned verifier. The struct alone is neither proof nor authorization.
"""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import hashlib, json, os, stat
from pathlib import Path
from recovery_latch_rc21 import RecoveryLatch, RecoveryRequired

@dataclass(frozen=True)
class RecoveryAttestation:
    session_id: str
    latch_digest: str
    witness_id: str
    observed_utc: datetime
    remote_ems_off: bool
    self_consumption: bool
    pcs_demand_zero: bool
    independent_of_thor: bool
    evidence_id: str

class AttestedRecoveryLatch(RecoveryLatch):
    """RC21 persistence plus strict external-attestation verification boundary."""
    def clear_after_independent_recovery(self, *args, **kwargs):
        raise RecoveryRequired('RC21 boolean-proof clearance retired; RC22 attestation required')

    def challenge(self):
        fd=os.open(self.path, os.O_RDONLY|os.O_NOFOLLOW)
        try:
            s=os.fstat(fd)
            if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_size>4096:raise RecoveryRequired('invalid latch')
            data=os.read(fd,4097)
            if len(data)>4096:raise RecoveryRequired('oversized latch')
            marker=json.loads(data)
            if marker.get('schema')!='SIGEN_RC21_RECOVERY_LATCH':raise RecoveryRequired('unrecognized latch')
            return marker['session_id'],hashlib.sha256(data).hexdigest()
        finally:os.close(fd)

    def clear_with_attestation(self, evidence, operator_ack, external_verifier, now=None):
        # Fail closed before any marker mutation.
        if not isinstance(evidence,RecoveryAttestation):raise RecoveryRequired('typed evidence required')
        if operator_ack is not True:raise RecoveryRequired('operator acknowledgement required')
        if not callable(external_verifier):raise RecoveryRequired('external verifier required')
        now=datetime.now(timezone.utc) if now is None else now
        if not isinstance(now,datetime) or now.tzinfo is None:raise RecoveryRequired('invalid current clock')
        t=evidence.observed_utc
        if not isinstance(t,datetime) or t.tzinfo is None:raise RecoveryRequired('timezone-aware evidence required')
        age=(now-t).total_seconds()
        if not -5<=age<=30:raise RecoveryRequired('stale or future evidence')
        if any(type(v) is not bool or not v for v in (evidence.remote_ems_off,evidence.self_consumption,evidence.pcs_demand_zero,evidence.independent_of_thor)):
            raise RecoveryRequired('physical handback proof incomplete')
        if not evidence.witness_id or not evidence.evidence_id:raise RecoveryRequired('missing witness identity')
        session,digest=self.challenge()
        if evidence.session_id!=session or evidence.latch_digest!=digest:raise RecoveryRequired('attestation not bound to active latch')
        # A real externally hosted proof verifier must authenticate the witness
        # and underlying readbacks. In tests this is a fake, not commissioning.
        if external_verifier(evidence) is not True:raise RecoveryRequired('external verifier denied')
        # Recheck to limit TOCTOU while clearing. RC21 inode matching remains.
        if self.challenge()!=(session,digest):raise RecoveryRequired('latch changed during verification')
        self._clear_matching(session)
''')
(root/'controller'/'supervised_session_rc22.py').write_text('''#!/usr/bin/env python3
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
''')
(root/'tests'/'test_rc22.py').write_text('''import unittest,tempfile,pathlib,sys
from dataclasses import replace
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'controller'))
from recovery_attestation_rc22 import AttestedRecoveryLatch,RecoveryAttestation,RecoveryRequired
import supervised_session_rc22 as session
import test_rc20
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=pathlib.Path(self.tmp.name)/'latch.json'
  self.latch=AttestedRecoveryLatch(self.path);self.latch.arm('operator-01')
  self.now=datetime(2026,11,4,18,tzinfo=timezone.utc)
  sid,digest=self.latch.challenge()
  self.e=RecoveryAttestation(sid,digest,'independent-host-a',self.now,True,True,True,True,'readback-01')
 def tearDown(self):self.tmp.cleanup()
 def clear(self,e=None,ack=True,verifier=lambda _:True):
  self.latch.clear_with_attestation(e or self.e,ack,verifier,self.now)
 def test_attested_clear_simulated(self):self.clear();self.assertFalse(self.path.exists())
 def test_retired_boolean_clear(self):
  with self.assertRaises(RecoveryRequired):self.latch.clear_after_independent_recovery('operator-01',lambda:True,True)
 def test_stale_evidence(self):
  with self.assertRaises(RecoveryRequired):self.clear(replace(self.e,observed_utc=self.now-timedelta(seconds=31)))
 def test_future_evidence(self):
  with self.assertRaises(RecoveryRequired):self.clear(replace(self.e,observed_utc=self.now+timedelta(seconds=6)))
 def test_wrong_session(self):
  with self.assertRaises(RecoveryRequired):self.clear(replace(self.e,session_id='another'))
 def test_wrong_digest(self):
  with self.assertRaises(RecoveryRequired):self.clear(replace(self.e,latch_digest='0'*64))
 def test_missing_witness(self):
  with self.assertRaises(RecoveryRequired):self.clear(replace(self.e,witness_id=''))
 def test_unverified_readbacks(self):
  for key in ('remote_ems_off','self_consumption','pcs_demand_zero','independent_of_thor'):
   with self.subTest(key=key),self.assertRaises(RecoveryRequired):self.clear(replace(self.e,**{key:False}))
 def test_external_denied(self):
  with self.assertRaises(RecoveryRequired):self.clear(verifier=lambda _:False)
 def test_operator_denied(self):
  with self.assertRaises(RecoveryRequired):self.clear(ack=False)
 def test_no_verifier(self):
  with self.assertRaises(RecoveryRequired):self.clear(verifier=None)
 def test_latch_persists_on_denial(self):
  try:self.clear(verifier=lambda _:False)
  except RecoveryRequired:pass
  self.assertTrue(self.path.exists())
 def test_replay_after_clear(self):
  self.clear()
  self.latch.arm('operator-02')
  with self.assertRaises(RecoveryRequired):self.clear()
 def test_live_cli_blocked(self):self.assertEqual(session.main(),2)
 def test_no_plant_control_in_attestation(self):
  src=(pathlib.Path(__file__).resolve().parents[1]/'controller'/'recovery_attestation_rc22.py').read_text()
  for token in ('import socket','import pymodbus','write_u32('):self.assertNotIn(token,src)
 def test_existing_session_core_preserved(self):
  self.assertTrue(callable(session.run_guarded))
''')
(root/'RELEASE_NOTES.md').write_text('''# SigenStor Phase 3B RC22 — Recovery attestation commissioning contract

**Status:** OFFLINE-ONLY commissioning integration. No live execution, no services, no inverter writes, no new authority grant. RC13 optimizer frozen.

RC22 adds session-bound external recovery attestation to the RC21 durable latch. The RC21 convenience callback accepting a boolean `True` is deliberately rejected by RC22's attested recovery-latch type. Clearing requires a marker digest and session match, signed-off physical state claims, <=30-second-old timestamp, operator acknowledgement, and a separately supplied external verifier. No supplied external verifier is commissioned, so the package is **not proof** of recovered plant state. RC21 legacy module is retained only to preserve accepted regression tests, not for use as a new live control path.

This closes an API-level gap; it does **not** solve off-host heartbeat expiration, independent power/network failure, system-wide exclusive writer control or full-slot physical acceptance. Those remain separate hard gates. RC22's session entrypoint is blocked by default.
''')
(root/'INDEPENDENT_RECOVERY_ACCEPTANCE.md').write_text('''# Independent recovery acceptance protocol (not yet passed)

## Architecture boundary
Recovery observer must execute on an independent physical host or qualified inverter-native fail-safe, not in the Thor LXC or another VM on Thor. Control communications, power, observation and watchdog continuity must survive the tested failure mode. Do not assert independence from separate containers on the same machine.

## Commissioning procedure (requires separate operator approval)
1. Commission authenticated producer-to-supervisor heartbeat with monotonic expiry tied to a particular supervised session and arm/disarm handshake.
2. Verify supervisor owns a recovery-only write path with exclusive authority and bounded registers; forbid 40034.
3. Confirm commissioned return-to-self-consumption command sequence and actual readbacks: PCS demand=0, PCS mode=2, Remote EMS=0, with independent physical/power observation.
4. Inject loss of LXC process, Thor host, control network, recovery network, missed heartbeats, delayed/duplicated heartbeat and conflicting writer; record detections, outcomes and worst-case latency.
5. Verify supervisory recovery and post-fault no-restart latch; obtain operator-reviewed evidence before enabling any session longer than already commissioned pilots.

## Explicit holds
No automatic recovery write path is shipped in RC22. No authenticated heartbeat service or externally verified attestation exists yet. A `True` callback in offline tests cannot constitute physical recovery proof. RC13 economic decisions are not execution authority. No unattended trading.
''')
(root/'install.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
sha256sum -c SHA256SUMS
python3 -B -W ignore::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -q
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc22
if [[ -e "$TARGET" ]]; then echo 'RC22 already installed; refusing overwrite'; exit 2; fi
mkdir -p "$TARGET"
cp -a controller accepted tests RELEASE_NOTES.md RECOVERY_DESIGN.md INDEPENDENT_RECOVERY_ACCEPTANCE.md SHA256SUMS "$TARGET"/
echo 'RC22 staged OFFLINE ONLY; no services or Modbus writes.'
''')
(root/'rollback.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc22
[[ -d "$TARGET" ]] || exit 0
rm -rf -- "$TARGET"
echo 'RC22 code removed; operational latch files remain untouched.'
''')
for p in (root/'install.sh',root/'rollback.sh'):p.chmod(0o755)
manifest=[]
for p in sorted(root.rglob('*')):
 if p.is_file() and p.name!='SHA256SUMS' and '__pycache__' not in p.parts:manifest.append(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(root).as_posix())
(root/'SHA256SUMS').write_text('\n'.join(manifest)+'\n')
result=subprocess.run(['python3','-B','-W','ignore::ResourceWarning','-m','unittest','discover','-s','tests','-p','test_*.py','-q'],cwd=root,capture_output=True,text=True)
(base/'rc22_test.log').write_text(result.stdout+result.stderr)
print('test result',result.returncode,result.stderr[-650:])
if result.returncode:raise SystemExit(1)
out=base/'SigenStor_Phase3B_RC22_Recovery_Attestation_OfflineTested.zip'
with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
 for p in sorted(root.rglob('*')):
  if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':z.write(p,p.relative_to(work))
with zipfile.ZipFile(out) as z:assert z.testzip() is None
print(out,out.stat().st_size)
