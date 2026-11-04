import unittest, tempfile, pathlib, datetime as dt, sys
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

class RC24Tests(unittest.TestCase):
 setUp=test_rc23.Tests.setUp
 tearDown=test_rc23.Tests.tearDown
 runpilot=test_rc23.Tests.runpilot
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
