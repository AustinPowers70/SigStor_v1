import unittest,tempfile,pathlib,sys
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
