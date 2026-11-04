import unittest,sys,pathlib
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
