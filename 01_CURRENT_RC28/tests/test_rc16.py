import sys,unittest,struct
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
from commissioning_transport_rc16 import RestrictedPlant,OfflineTransportHarness,CommissioningBlocked,main
class Fake:
 simulation_only=True
 def __init__(self):self.reg={40029:0,40031:2,40001:0,40032:0};self.writes=[];self.closed=False;self.fail=False
 def read_holding(self,a):return self.reg[a]
 def call(self,fc,payload):return b'\x04'+struct.pack('>I',self.reg[40001])
 def write(self,a,v):
  self.writes.append((a,v))
  if self.fail:raise TimeoutError('ambiguous')
  self.reg[a]=v
 def write_u32(self,a,v):self.write(a,v)
 def close(self):self.closed=True
class Tests(unittest.TestCase):
 def setUp(self):self.f=Fake();self.log=[];self.p=RestrictedPlant(self.f,lambda *x:self.log.append(x))
 def test_allowlist(self):
  for a,v in [(40034,100),(40029,2),(40031,1),(40001,0)]:
   with self.assertRaises(CommissioningBlocked):self.p.write(a,v)
  self.assertFalse(self.f.writes)
 def test_u32_allowlist(self):
  for a,v in [(40034,0),(40001,999),(40032,600)]:
   with self.assertRaises(CommissioningBlocked):self.p.write_u32(a,v)
 def test_cannot_arbitrary_call(self):
  with self.assertRaises(CommissioningBlocked):self.p.call(16,b'x')
 def test_uncertain_write_recorded(self):
  self.f.fail=True
  with self.assertRaises(TimeoutError):self.p.write(40031,2)
  self.assertEqual([x[0] for x in self.log],['WRITE_INTENT','WRITE_OUTCOME_UNCERTAIN'])
 def test_charge_and_handback(self):
  h=OfflineTransportHarness(self.f,lambda *x:self.log.append(x))
  h.start('GRID_CHARGE');self.assertTrue(h.handback());h.close()
  self.assertTrue(self.f.closed);self.assertEqual(self.f.reg[40029],0)
 def test_export_and_handback(self):
  h=OfflineTransportHarness(self.f,lambda *x:self.log.append(x))
  h.start('EXPORT');self.assertTrue(h.handback());h.close()
  self.assertEqual(self.f.reg[40001],0)
 def test_reject_live_connection(self):
  self.f.simulation_only=False
  with self.assertRaises(CommissioningBlocked):OfflineTransportHarness(self.f,lambda *x:None)
 def test_close_blocks_writes(self):
  self.p.close()
  with self.assertRaises(CommissioningBlocked):self.p.write(40029,0)
 def test_no_live_entry(self):self.assertEqual(main(),2)
 def test_no_40034_written(self):
  h=OfflineTransportHarness(self.f,lambda *x:self.log.append(x));h.start('EXPORT');h.handback()
  self.assertNotIn(40034,[x[0] for x in self.f.writes])
if __name__=='__main__':unittest.main()
