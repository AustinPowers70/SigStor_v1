from pathlib import Path
import shutil, subprocess, zipfile, hashlib, re
base=Path('/mnt/data'); work=base/'work_rc24'; root=work/'SigenStor_Phase3B_RC24'
if work.exists():shutil.rmtree(work)
shutil.copytree(base/'work_rc23'/'SigenStor_Phase3B_RC23',root, ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
f=root/'controller'/'attended_pilot_rc23.py'
s=f.read_text()
s=s.replace('acquired=isolated=attempted=handback_ok=restored=False','acquired=isolated=attempted=handback_ok=restored=False')
old='''        if panel.is_active() is not True:raise PilotHold('authority panel baseline missing')
        panel.stop();isolated=True
        if panel.is_active() is not False:raise PilotHold('authority panel isolation failed')
        # Persist a fail-closed interlock BEFORE any live-capable write attempt.
        latch.arm(permit.session_id)
        record('PILOT_LATCH_ARMED')'''
new='''        if panel.is_active() is not True:raise PilotHold('authority panel baseline missing')
        # Durable marker PRECEDES any change to control authority. Even a partial
        # panel-stop failure must not leave an unlatched unknown control state.
        latch.arm(permit.session_id)
        record('PILOT_LATCH_ARMED')
        isolated=True  # stop() can partially succeed and then raise
        record('PILOT_PANEL_STOP_ATTEMPT')
        panel.stop()
        if panel.is_active() is not False:raise PilotHold('authority panel isolation failed')'''
assert old in s
s=s.replace(old,new)
# Existing RC23 has same safe invariant: preserve latch for any abort.
f.write_text(s)
(root/'tests'/'test_rc24.py').write_text('''import unittest, tempfile, pathlib, datetime as dt, sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import test_rc23
Panel=test_rc23.Panel
from attended_pilot_rc23 import PilotHold

class FaultPanel(Panel):
 def __init__(self, scenario):super().__init__();self.scenario=scenario;self.start_calls=0
 def stop(self):
  if self.scenario in ('partial_stop','restore_failure'):self.active=False;raise RuntimeError('panel stop exception after isolation')
  if self.scenario=='unchanged':return
  self.active=False
 def start(self):
  self.start_calls+=1
  if self.scenario=='restore_failure':raise RuntimeError('panel start failed')
  self.active=True

class RC24Tests(BaseTests):
 def test_partial_panel_stop_latched_and_restored(self):
  self.panel=FaultPanel('partial_stop')
  with self.assertRaises(PilotHold):self.runpilot()
  self.assertTrue(self.path.exists());self.assertEqual(self.panel.start_calls,1)
  self.assertTrue(self.panel.active);self.assertFalse(self.plant.writes)
  names=[e for e,_ in self.events]
  self.assertLess(names.index('PILOT_LATCH_ARMED'),names.index('PILOT_PANEL_STOP_ATTEMPT'))
 def test_failed_isolation_verification_latched(self):
  self.panel=FaultPanel('unchanged')
  with self.assertRaises(PilotHold):self.runpilot()
  self.assertTrue(self.path.exists());self.assertTrue(self.panel.active)
  self.assertEqual(self.plant.writes,[])
 def test_failed_isolation_and_restore_retains_latch(self):
  self.panel=FaultPanel('restore_failure')
  with self.assertRaises(PilotHold):self.runpilot()
  self.assertTrue(self.path.exists());self.assertEqual(self.plant.writes,[])
 def test_existing_latch_prevents_panel_stop(self):
  from recovery_latch_rc21 import RecoveryLatch
  RecoveryLatch(self.path).arm('other-session')
  self.panel=FaultPanel('partial_stop')
  with self.assertRaises(PilotHold):self.runpilot()
  self.assertTrue(self.panel.active);self.assertEqual(self.panel.start_calls,0)
 def test_no_side_effect_before_baseline_authority_check(self):
  self.panel.active=False
  with self.assertRaises(PilotHold):self.runpilot()
  self.assertFalse(self.path.exists());self.assertFalse(self.plant.writes)
''')
# Tests were inherited from parent test class which adds 20 tests; avoid duplication by change base class to object and delegate setup/calls, 5 tests only
p=root/'tests'/'test_rc24.py'; ss=p.read_text().replace('class RC24Tests(BaseTests):','class RC24Tests(unittest.TestCase):\n setUp=test_rc23.Tests.setUp\n tearDown=test_rc23.Tests.tearDown\n runpilot=test_rc23.Tests.runpilot'); p.write_text(ss)
(root/'RELEASE_NOTES_RC24.md').write_text('''# RC24 — Authority isolation transaction hardening\n\nRC23 verified on Thor (297/297). RC24 moves the durable recovery latch to BEFORE the authority-panel stop attempt and marks isolation as potentially changed before invoking stop. Partial stop failure now enters the attempted-restoration path; the latch persists after any abort, including a restored panel, pending controlled inspection. No inverter writes, no live CLI, no added services, no independent host-loss recovery claim. RC13, 40034 and all charge/export limits remain unchanged.\n\nScope: 5 targeted RC24 fault-injection tests; original 297 tests unchanged.\n''')
(root/'install.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
sha256sum -c SHA256SUMS
python3 -B -W ignore::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -q
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc24
if [[ -e "$TARGET" ]]; then echo 'RC24 already installed; refusing overwrite'; exit 2; fi
mkdir -p "$TARGET"
cp -a controller accepted tests *.md SHA256SUMS "$TARGET"/
echo 'RC24 staged: authority isolation hardening OFFLINE ONLY; no services or Modbus writes.'
''')
(root/'install.sh').chmod(0o755)
(root/'rollback.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' 'RC24 staging has no services or active writers. Retain the prior RC23 tree as rollback baseline.'
''')
(root/'rollback.sh').chmod(0o755)
files=sorted(p for p in root.rglob('*') if p.is_file() and p.name!='SHA256SUMS')
(root/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root)}\n' for p in files))
result=subprocess.run(['python3','-B','-W','ignore::ResourceWarning','-m','unittest','discover','-s','tests','-p','test_*.py','-q'],cwd=root,capture_output=True,text=True)
(base/'rc24_test.log').write_text(result.stdout+result.stderr)
print('test exit:',result.returncode,'\n', (result.stdout+result.stderr)[-1800:])
if result.returncode:raise SystemExit(1)
zip_path=base/'SigenStor_Phase3B_RC24_Authority_Isolation_OfflineTested.zip'
with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED) as z:
 for p in sorted(root.rglob('*')):
  if p.is_file():z.write(p,p.relative_to(work))
with zipfile.ZipFile(zip_path) as z:assert z.testzip() is None
print(zip_path, zip_path.stat().st_size)
