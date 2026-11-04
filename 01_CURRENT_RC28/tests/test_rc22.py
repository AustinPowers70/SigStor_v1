import unittest,tempfile,pathlib,sys
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
