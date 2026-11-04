from pathlib import Path
import zipfile,shutil,subprocess,hashlib
base=Path('/mnt/data'); work=base/'work_rc21'; root=work/'SigenStor_Phase3B_RC21'
if work.exists():shutil.rmtree(work)
work.mkdir()
with zipfile.ZipFile(base/'SigenStor_Phase3B_RC20_Supervised_Integration.zip') as z:
    for info in z.infolist():
        name=Path(info.filename)
        if name.parts[0]!='SigenStor_Phase3B_RC20' or '__pycache__' in name.parts or name.suffix=='.pyc':continue
        dest=root.joinpath(*name.parts[1:]);
        if info.is_dir():dest.mkdir(parents=True,exist_ok=True);continue
        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(info))
(root/'controller'/'recovery_latch_rc21.py').write_text('''#!/usr/bin/env python3
"""Durable fail-closed session latch. No plant, Modbus, or service APIs.

A marker is persisted before any session start. If the process is interrupted,
next launch refuses until independent physical recovery has been checked.
This protects only cooperating RC21 entry points; NOT independent recovery.
"""
import json
import os
import stat
from pathlib import Path
from datetime import datetime,timezone

class RecoveryRequired(RuntimeError): pass

class RecoveryLatch:
    def __init__(self,path):
        self.path=Path(path)
        if not self.path.is_absolute():raise ValueError('absolute latch path required')
        if self.path.is_symlink() or self.path.parent.is_symlink():raise RecoveryRequired('symlink not permitted')
        if not self.path.parent.is_dir():raise RecoveryRequired('latch directory absent')
    def _syncdir(self):
        fd=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
    def exists(self):
        if self.path.is_symlink():raise RecoveryRequired('symlink marker')
        return self.path.exists()
    def arm(self,session_id):
        if not isinstance(session_id,str) or not session_id or len(session_id)>128:raise ValueError('invalid session ID')
        # O_EXCL makes launch atomic across cooperating processes.
        try:fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        except FileExistsError as exc:raise RecoveryRequired('existing recovery-required latch') from exc
        try:
            payload=json.dumps({'schema':'SIGEN_RC21_RECOVERY_LATCH','session_id':session_id,'armed_utc':datetime.now(timezone.utc).isoformat(),'state':'RECOVERY_REQUIRED_UNTIL_VERIFIED'},sort_keys=True).encode()+b'\\n'
            with os.fdopen(fd,'wb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
            self._syncdir()
        except BaseException:
            # Keep any marker after an uncertain persistence outcome, fail closed.
            raise
    def clear_after_verified_completion(self,session_id,verified):
        if verified is not True:raise RecoveryRequired('verified handback and panel restoration required')
        self._clear_matching(session_id)
    def clear_after_independent_recovery(self,session_id,physical_proof,operator_ack):
        # No public CLI: a separately qualified recovery implementation must supply proof.
        if not callable(physical_proof) or physical_proof() is not True or operator_ack is not True:
            raise RecoveryRequired('independent physical proof and operator approval required')
        self._clear_matching(session_id)
    def _clear_matching(self,session_id):
        fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            st=os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:raise RecoveryRequired('invalid latch file')
            data=os.read(fd,4096)
            if len(data)==4096:raise RecoveryRequired('oversized latch')
            value=json.loads(data)
            if value.get('schema')!='SIGEN_RC21_RECOVERY_LATCH' or value.get('session_id')!=session_id:
                raise RecoveryRequired('session identity mismatch')
            # Concurrent replacement must not be mistaken for verified old marker.
            current=os.lstat(self.path)
            if (st.st_ino,st.st_dev)!=(current.st_ino,current.st_dev):raise RecoveryRequired('latch changed')
            os.unlink(self.path);self._syncdir()
        finally:os.close(fd)
''')
(root/'controller'/'supervised_session_rc21.py').write_text('''#!/usr/bin/env python3
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
''')
(root/'tests'/'test_rc21.py').write_text('''import unittest,tempfile,pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'controller'))
from recovery_latch_rc21 import RecoveryLatch,RecoveryRequired
import supervised_session_rc21 as r
import test_rc20
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=pathlib.Path(self.tmp.name)/'recovery-latch.json'
        self.helper=test_rc20.Tests()
    def tearDown(self):self.tmp.cleanup()
    def test_success_clears_latch(self):
        kw,*_=self.helper.configure();self.assertTrue(r.run_guarded(latch_path=self.path,**kw)['handback_verified']);self.assertFalse(self.path.exists())
    def test_uncertain_handback_latches(self):
        kw,plant,*_=self.helper.configure();plant.fail_handback=True
        with self.assertRaises(Exception):r.run_guarded(latch_path=self.path,**kw)
        self.assertTrue(self.path.exists())
    def test_next_session_refused_before_write(self):
        RecoveryLatch(self.path).arm('operator-session-1')
        kw,plant,*_=self.helper.configure()
        with self.assertRaises(RecoveryRequired):r.run_guarded(latch_path=self.path,**kw)
        self.assertEqual(plant.writes,[])
    def test_qualification_abort_latches(self):
        kw,plant,*_=self.helper.configure(qualify=lambda _: {'valid':False})
        with self.assertRaises(Exception):r.run_guarded(latch_path=self.path,**kw)
        self.assertTrue(self.path.exists())
    def test_operator_cannot_clear_without_physical_proof(self):
        latch=RecoveryLatch(self.path);latch.arm('a')
        with self.assertRaises(RecoveryRequired):latch.clear_after_independent_recovery('a',lambda:False,True)
        with self.assertRaises(RecoveryRequired):latch.clear_after_independent_recovery('a',lambda:True,False)
        self.assertTrue(self.path.exists())
    def test_identity_mismatch_refused(self):
        latch=RecoveryLatch(self.path);latch.arm('a')
        with self.assertRaises(RecoveryRequired):latch.clear_after_independent_recovery('b',lambda:True,True)
    def test_verified_manual_recovery_can_clear(self):
        latch=RecoveryLatch(self.path);latch.arm('a')
        latch.clear_after_independent_recovery('a',lambda:True,True);self.assertFalse(self.path.exists())
    def test_symlink_marker_refused(self):
        target=pathlib.Path(self.tmp.name)/'target';target.write_text('dummy');self.path.symlink_to(target)
        with self.assertRaises(RecoveryRequired):RecoveryLatch(self.path)
    def test_no_live_entry(self):self.assertEqual(r.main(),2)
    def test_no_plant_in_latch(self):
        source=(pathlib.Path(__file__).resolve().parents[1]/'controller'/'recovery_latch_rc21.py').read_text()
        for x in ('socket','pymodbus','write_u32','40034'):self.assertNotIn(x,source)
if __name__=='__main__':unittest.main()
''')
(root/'RELEASE_NOTES.md').write_text('''# SigenStor Phase 3B RC21 — Durable recovery latch\n\n## Status\nOffline-only integration, never a production live controller. No automated dispatch or Modbus writes. RC13 remains frozen.\n\n## Change\nRC20 releases its process lock after an uncertain handback; this is necessary for process cleanup but insufficient to prevent a new process acquiring authority. RC21 adds an on-disk recovery-required latch, atomically created and fsynced before any injected session. Failed handback, aborts, process death and uncertain state leave it present. Cooperating RC21 sessions refuse while present. A successful simulated session with verified handback and panel restoration clears it. Manual recovery clearing requires a separately implemented, independently verified physical proof and explicit operator acknowledgement. There is deliberately no CLI to clear the latch.\n\n## Critical limits\n- A local latch cannot return an inverter to self-consumption when Thor/LXC/network is unavailable.\n- Other controllers not enforcing this latch can still write; actual single-writer enforcement must be integrated across all producers.\n- The recovery proof callback is an uncommissioned contract, **not** physical recovery evidence.\n- No real plant transport is wired to RC21. No systemd units changed.\n- Full-slot commissioning blocked pending independent recovery and supervised commissioning acceptance.\n''')
(root/'RECOVERY_DESIGN.md').write_text('''# RC21 Recovery design / next commissioning gate\n\n**State model:** IDLE → LATCH_ARMED → SESSION_ACTIVE → VERIFIED_HANDBACK → IDLE, or any failure → RECOVERY_REQUIRED.\n\n**Interlock:** per-session durable O_EXCL latch before control attempt; on uncertain outcomes retain file. An independent observer must determine actual physical state. Do not remove the marker manually, or rely on process lock as recovery evidence.\n\n**Not yet implemented:** externally hosted recovery supervisor with separately maintained power and communications, validated ability to zero PCS/set self-consumption/disable Remote EMS following a forced Thor/LXC/network outage, independent heartbeat-expiry testing, and proof-bound manual release. Modbus writer coordination across authority-panel and earlier pilots needs explicit system-wide enforcement.\n\n**Release criteria:** independent recovery demonstration, wired real readback/audit, exclusive authority under failure, operator approval and monitoring, bounded live commissioning and grid-side evidence. This package intentionally has no live entrypoint.\n''')
(root/'install.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
sha256sum -c SHA256SUMS
python3 -B -W ignore::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -q
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc21
if [[ -e "$TARGET" ]]; then echo 'RC21 already installed; refusing overwrite'; exit 2; fi
mkdir -p "$TARGET"
cp -a controller accepted tests RELEASE_NOTES.md RECOVERY_DESIGN.md SHA256SUMS "$TARGET"/
echo 'RC21 staged OFFLINE ONLY; no services or Modbus writes.'
''')
(root/'rollback.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc21
[[ -d "$TARGET" ]] || exit 0
# Do not delete operational recovery latches; those belong outside the package.
rm -rf -- "$TARGET"
echo 'RC21 code removed. No services changed.'
''')
for p in [root/'install.sh',root/'rollback.sh']:p.chmod(0o755)
manifest=[]
for p in sorted(root.rglob('*')):
    if p.is_file() and p.name!='SHA256SUMS' and '__pycache__' not in p.parts:
        manifest.append(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(root).as_posix())
(root/'SHA256SUMS').write_text('\n'.join(manifest)+'\n')
result=subprocess.run(['python3','-B','-W','ignore::ResourceWarning','-m','unittest','discover','-s','tests','-p','test_*.py','-q'],cwd=root,capture_output=True,text=True)
(base/'rc21_test.log').write_text(result.stdout+result.stderr)
print('test result',result.returncode, result.stderr[-650:]);
if result.returncode:raise SystemExit(1)
out=base/'SigenStor_Phase3B_RC21_Recovery_Latch_OfflineTested.zip'
with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for p in sorted(root.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':z.write(p,p.relative_to(work))
print(out,out.stat().st_size)
