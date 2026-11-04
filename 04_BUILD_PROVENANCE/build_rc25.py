from pathlib import Path
import shutil, subprocess, zipfile, hashlib, textwrap
base=Path('/mnt/data'); work=base/'work_rc25'; root=work/'SigenStor_Phase3B_RC25'
if work.exists():shutil.rmtree(work)
shutil.copytree(base/'work_rc24'/'SigenStor_Phase3B_RC24',root,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
p=root/'controller'/'attended_pilot_rc23.py'; s=p.read_text()
anchor="    now=utcnow();permit.validate(now)"
assert anchor in s
s=s.replace(anchor,"""    # This is an INJECTION-ONLY rehearsal runner. Mere method compatibility
    # must never let an actual Modbus adapter through this test interface.
    if getattr(plant,'simulation_only',None) is not True:
        raise PilotHold('RC25 simulation boundary: real plant not accepted')
"""+anchor)
p.write_text(s)
p=root/'tests'/'test_rc23.py';s=p.read_text();s=s.replace('class Plant:\n def __init__(self):','class Plant:\n simulation_only=True\n def __init__(self):');p.write_text(s)
(root/'controller'/'pilot_evidence_rc25.py').write_text('''#!/usr/bin/env python3
"""Offline/read-only evidence classification for attended-pilot audit events.

No inverter transport, no Modbus writes. Audit events alone cannot show physical
battery energy transfer. Actual delivered power needs separately observed,
time-aligned grid/battery measurements and commissioning review.
"""
import argparse
import json
from pathlib import Path

SCHEMA='SIGEN_PHASE3B_RC25_PILOT_AUDIT_REVIEW'
class EvidenceHold(ValueError): pass

def assess(events):
    if not isinstance(events,list): raise EvidenceHold('events list required')
    names=[]; session=None; sample_count=0; aborted=False
    for item in events:
        if not isinstance(item,dict) or set(item)!={'event','detail'}:raise EvidenceHold('invalid event envelope')
        name=item['event']; detail=item['detail']
        if not isinstance(name,str) or not isinstance(detail,dict):raise EvidenceHold('invalid event')
        sid=detail.get('session_id')
        if type(sid) is not str or not sid:raise EvidenceHold('session missing')
        if session is None:session=sid
        if session!=sid:raise EvidenceHold('mixed session evidence')
        names.append(name)
        if name=='PILOT_SAMPLE':
            import math
            if any(type(detail.get(k)) not in (int,float) or not math.isfinite(detail[k]) for k in ('soc_pct','battery_kw','grid_kw')):raise EvidenceHold('invalid sample')
            if not 0<=detail['soc_pct']<=100:raise EvidenceHold('invalid SOC')
            sample_count+=1
        if name=='PILOT_ABORT':aborted=True
    started='PILOT_START_ATTEMPT' in names
    handed='PILOT_HANDBACK_VERIFIED' in names
    panel='PILOT_PANEL_RESTORED' in names
    arm='PILOT_LATCH_ARMED' in names
    correct_order=False
    if arm and started and handed and panel:
        correct_order=names.index('PILOT_LATCH_ARMED')<names.index('PILOT_START_ATTEMPT')<names.index('PILOT_HANDBACK_VERIFIED')<names.index('PILOT_PANEL_RESTORED')
    complete=correct_order and sample_count>=2 and not aborted and not any(x.startswith('PILOT_CRITICAL') for x in names)
    return {'schema':SCHEMA,'session_id':session,'status':'AUDIT_SEQUENCE_COMPLETE' if complete else 'HOLD_INCOMPLETE_OR_ABORTED',
            'sample_events':sample_count,'handback_event_recorded':handed,'panel_restoration_event_recorded':panel,
            'grid_side_battery_delivery_verified':False,'host_loss_recovery_verified':False,
            'autonomous_dispatch':False,'modbus_writes_issued_by_assessor':0}

def main(argv=None):
    parser=argparse.ArgumentParser(description='Offline review of JSONL audit envelope; never actuates')
    parser.add_argument('--audit-jsonl',type=Path)
    args=parser.parse_args(argv)
    if args.audit_jsonl is None:
        print('RC25_READONLY_AUDIT_ASSESSOR: NO LIVE CLI; MODBUS_WRITES=0');return 0
    try:
        if args.audit_jsonl.stat().st_size>2_000_000:raise EvidenceHold('audit too large')
        with args.audit_jsonl.open('r',encoding='utf-8') as f:events=[json.loads(row) for row in f if row.strip()]
        out=assess(events);print(json.dumps(out,sort_keys=True));return 0 if out['status']=='AUDIT_SEQUENCE_COMPLETE' else 2
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print('RC25_HOLD',type(exc).__name__,str(exc),'MODBUS_WRITES=0');return 2
if __name__=='__main__':raise SystemExit(main())
''')
(root/'tests'/'test_rc25.py').write_text('''import unittest,sys,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'controller'))
import test_rc23
from attended_pilot_rc23 import PilotHold
from pilot_evidence_rc25 import assess, EvidenceHold, main

class RC25Tests(unittest.TestCase):
 setUp=test_rc23.Tests.setUp
 tearDown=test_rc23.Tests.tearDown
 runpilot=test_rc23.Tests.runpilot
 def test_simulated_pilot_allowed(self):
  self.assertEqual(self.runpilot()['status'],'SIMULATED_PILOT_COMPLETE')
 def test_real_transport_rejected_pre_side_effects(self):
  class RealLooking(test_rc23.Plant):simulation_only=False
  self.plant=RealLooking()
  with self.assertRaisesRegex(PilotHold,'simulation boundary'):self.runpilot()
  self.assertFalse(self.plant.writes);self.assertFalse(self.lock.held);self.assertFalse(self.path.exists())
 def test_untagged_plant_rejected(self):
  self.plant.simulation_only=None
  with self.assertRaises(PilotHold):self.runpilot()
  self.assertFalse(self.plant.writes)
 def test_truthy_string_not_simulator(self):
  self.plant.simulation_only='True'
  with self.assertRaises(PilotHold):self.runpilot()
 def test_simulated_success_not_power_proof(self):
  self.runpilot()
  rows=[{'event':e,'detail':d} for e,d in self.events]
  r=assess(rows);self.assertEqual(r['status'],'AUDIT_SEQUENCE_COMPLETE')
  self.assertFalse(r['grid_side_battery_delivery_verified']);self.assertFalse(r['host_loss_recovery_verified'])
 def test_missing_handback_is_hold(self):
  self.runpilot()
  rows=[{'event':e,'detail':d} for e,d in self.events if e!='PILOT_HANDBACK_VERIFIED']
  self.assertEqual(assess(rows)['status'],'HOLD_INCOMPLETE_OR_ABORTED')
 def test_missing_restoration_is_hold(self):
  self.runpilot()
  rows=[{'event':e,'detail':d} for e,d in self.events if e!='PILOT_PANEL_RESTORED']
  self.assertEqual(assess(rows)['status'],'HOLD_INCOMPLETE_OR_ABORTED')
 def test_abort_is_hold(self):
  with self.assertRaises(PilotHold):self.runpilot(presence=lambda:self.clock.n<6)
  r=assess([{'event':e,'detail':d} for e,d in self.events]);self.assertEqual(r['status'],'HOLD_INCOMPLETE_OR_ABORTED')
 def test_mixed_session_denied(self):
  self.runpilot();rows=[{'event':e,'detail':d.copy()} for e,d in self.events]
  rows[-1]['detail']['session_id']='different'
  with self.assertRaises(EvidenceHold):assess(rows)
 def test_tampered_soc_denied(self):
  self.runpilot();rows=[{'event':e,'detail':d.copy()} for e,d in self.events]
  next(x for x in rows if x['event']=='PILOT_SAMPLE')['detail']['soc_pct']=110.
  with self.assertRaises(EvidenceHold):assess(rows)
 def test_invalid_empty_evidence_hold(self):
  self.assertEqual(assess([])['status'],'HOLD_INCOMPLETE_OR_ABORTED')
 def test_no_live_cli(self):self.assertEqual(main([]),0)
''')
(root/'RELEASE_NOTES_RC25.md').write_text('''# RC25 — Rehearsal/live separation and commissioning evidence review

RC24 was independently validated on Thor (302/302), with no active services or inverter writes. RC25 explicitly rejects real/untagged Modbus adapters at the attended-pilot *injection-only* API. The offline test fixture is explicitly tagged `simulation_only=True`. This is a guard against accidental binding, not a cryptographic trust boundary: Python caller code can still impersonate fake adapters; therefore RC25 is not a live execution controller.

A new read-only assessor accepts a JSONL list of event/detail envelopes and reports sequence completeness and sample-event coverage. It deliberately **never** upgrades audit events or aggregate grid power into verified physical grid-side battery delivery. A complete simulated audit remains simulated evidence only.

No new systemd services, autonomous dispatch, real actuator CLI or changes to RC13, 40034, 500 W charge and 650 W export limits. Independently verified host-loss recovery remains unresolved and full-slot control not commissioned.
''')
(root/'install.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
sha256sum -c SHA256SUMS
python3 -B -W ignore::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -q
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc25
if [[ -e "$TARGET" ]]; then echo 'RC25 already installed; refusing overwrite'; exit 2; fi
mkdir -p "$TARGET"
cp -a controller accepted tests *.md SHA256SUMS "$TARGET"/
echo 'RC25 staged: REHEARSAL AND AUDIT ONLY; no services or Modbus writes.'
''')
(root/'install.sh').chmod(0o755)
(root/'rollback.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' 'RC25 is staged-only. RC24 remains intact for rollback.'
''')
(root/'rollback.sh').chmod(0o755)
files=sorted(p for p in root.rglob('*') if p.is_file() and p.name!='SHA256SUMS')
(root/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root)}\n' for p in files))
r=subprocess.run(['python3','-B','-W','ignore::ResourceWarning','-m','unittest','discover','-s','tests','-p','test_*.py','-q'],cwd=root,capture_output=True,text=True)
(base/'rc25_test.log').write_text(r.stdout+r.stderr)
print('exit',r.returncode, 'end:',(r.stdout+r.stderr)[-900:]);
if r.returncode:raise SystemExit(1)
zip_path=base/'SigenStor_Phase3B_RC25_Rehearsal_Evidence_OfflineTested.zip'
with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED) as z:
 for p in sorted(root.rglob('*')):
  if p.is_file():z.write(p,p.relative_to(work))
with zipfile.ZipFile(zip_path) as z:assert z.testzip() is None
print(zip_path,zip_path.stat().st_size)
