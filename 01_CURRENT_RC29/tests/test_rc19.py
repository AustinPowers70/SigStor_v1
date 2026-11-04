import unittest,sys,datetime as dt,importlib.util
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
import commissioning_handoff_rc19 as h

NOW=dt.datetime(2026,11,4,18,0,tzinfo=dt.timezone.utc)
class HandoffTests(unittest.TestCase):
    def report(self,plant=None):
        # Invalid documents must fail closed without propagating dispatch.
        return h.evaluate(now=NOW,candidate={},settings={},authority={},r5={},plant=plant)
    def test_invalid_source_hold(self):
        r=self.report();self.assertEqual(r['status'],'HOLD_FOR_SUPERVISED_COMMISSIONING');self.assertIn('SOURCE_OR_CONTRACT_INVALID',r['issues'])
    def test_no_writes(self):self.assertEqual(self.report()['modbus_writes'],0)
    def test_no_auto(self):self.assertFalse(self.report()['autonomous_dispatch'])
    def test_no_live(self):self.assertFalse(self.report()['live_execution_enabled'])
    def test_no_grid_side_claim(self):self.assertFalse(self.report()['grid_side_battery_delivery_verified'])
    def test_missing_plant(self):self.assertIn('CURRENT_PLANT_STATE_NOT_CHECKED',self.report()['issues'])
    def test_unhanded_plant(self):self.assertIn('PLANT_HANDBACK_NOT_VERIFIED',self.report({})['issues'])
    def test_stale_plant(self):
        p=dict(plant_handback_verified=True,remote_ems_off=True,self_consumption=True,pcs_zero=True,timestamp_utc='2026-11-04T17:55:00Z')
        self.assertIn('PLANT_OBSERVATION_STALE',self.report(p)['issues'])
    def test_good_plant_does_not_unlock(self):
        p=dict(plant_handback_verified=True,remote_ems_off=True,self_consumption=True,pcs_zero=True,timestamp_utc='2026-11-04T18:00:00Z')
        r=self.report(p);self.assertTrue(r['plant_handback_checked']);self.assertFalse(r['live_execution_enabled']);self.assertIn('INDEPENDENT_HOST_NETWORK_LOSS_RECOVERY_NOT_VERIFIED',r['issues'])
    def test_execute_blocked(self):self.assertEqual(h.main(['--execute-slot']),2)
    def test_no_write_interface(self):
        s=Path(h.__file__).read_text();self.assertNotIn('write_u32(',s);self.assertNotIn('40034,',s)
    def test_naive_rejected(self):
        with self.assertRaises(h.HandoffError):h.evaluate(now=dt.datetime(2026,11,4),candidate={},settings={},authority={},r5={})
    def test_recovery_is_not_self_attested(self):self.assertFalse(self.report()['independent_recovery_accepted'])
if __name__=='__main__':unittest.main()
