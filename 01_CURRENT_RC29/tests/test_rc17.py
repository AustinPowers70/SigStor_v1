import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
import real_transport_rc17 as r
class Fake:
 def __init__(self,off=0,mode=2,pcs=b'\x04\x00\x00\x00\x00'):
  self.off,self.mode,self.pcs=off,mode,pcs;self.closed=False;self.writes=[]
 def read_holding(self,a):return {40029:self.off,40031:self.mode}[a]
 def call(self,fc,p):
  assert fc==3 and p==bytes.fromhex('9c410002');return self.pcs
 def write(self,*a):self.writes.append(a)
 def write_u32(self,*a):self.writes.append(a)
 def close(self):self.closed=True
class Tests(unittest.TestCase):
 def test_verified_state(self):
  f=Fake();x=r.preview_handback_contract(f,lambda *a:None)
  self.assertTrue(x['handback_state_verified']);self.assertEqual(x['modbus_writes'],0);self.assertTrue(f.closed);self.assertFalse(f.writes)
 def test_ems_on_rejected(self):self.assertFalse(r.preview_handback_contract(Fake(off=1),lambda *a:None)['handback_state_verified'])
 def test_mode_wrong_rejected(self):self.assertFalse(r.preview_handback_contract(Fake(mode=3),lambda *a:None)['handback_state_verified'])
 def test_pcs_nonzero_rejected(self):self.assertFalse(r.preview_handback_contract(Fake(pcs=b'\x04\x00\x00\x02\x8a'),lambda *a:None)['handback_state_verified'])
 def test_no_instantiate(self):
  with self.assertRaises(r.LiveTransportUnavailable):r.SupervisedPlantAdapter(None,lambda *a:None)
 def test_no_simulated(self):
  f=Fake();f.simulation_only=True
  with self.assertRaises(r.LiveTransportUnavailable):r.SupervisedPlantAdapter(f,lambda *a:None)
 def test_no_direct_start(self):
  f=Fake();p=r.SupervisedPlantAdapter(f,lambda *a:None)
  with self.assertRaises(r.LiveTransportUnavailable):p.start('EXPORT',650)
  self.assertFalse(f.writes);p.close()
 def test_no_direct_write(self):
  f=Fake();p=r.SupervisedPlantAdapter(f,lambda *a:None)
  for fn in (lambda:p.write(40029,1),lambda:p.write_u32(40001,650)):
   with self.assertRaises(r.LiveTransportUnavailable):fn()
  self.assertFalse(f.writes);p.close()
 def test_read_allowlist(self):
  f=Fake();p=r.SupervisedPlantAdapter(f,lambda *a:None)
  with self.assertRaises(Exception):p.read_holding(40034)
  p.close()
 def test_close_on_read_error(self):
  class Bad(Fake):
   def read_holding(self,a):raise RuntimeError('offline')
  f=Bad()
  with self.assertRaises(RuntimeError):r.preview_handback_contract(f,lambda *a:None)
  self.assertTrue(f.closed)
 def test_audit_required(self):
  with self.assertRaises(Exception):r.SupervisedPlantAdapter(Fake(),None)
 def test_cli_disabled(self):self.assertEqual(r.main(),2)
if __name__=='__main__':unittest.main()
