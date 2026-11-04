import sys,struct,tempfile,unittest,json,pathlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
import soc_acquisition_rc8 as s
class FakeSocket:
 def __init__(self,raw):self.raw=raw;self.sent=b'';self.closed=False
 def settimeout(self,n):pass
 def sendall(self,data):self.sent=data
 def recv(self,n):chunk=self.raw[:n];self.raw=self.raw[n:];return chunk
 def close(self):self.closed=True
class Tests(unittest.TestCase):
 def packet(self,soc=750,fc=4,unit=247):
  data=bytearray(68);data[18:20]=struct.pack('>H',soc)
  return struct.pack('>HHHB',1,0,71,unit)+bytes([fc,68])+bytes(data)
 def test_decode(self):self.assertEqual(s.decode_response(self.packet()[:7],self.packet()[7:],1),75)
 def test_bad_unit(self):
  with self.assertRaises(s.AcquisitionError):s.decode_response(self.packet(unit=1)[:7],self.packet(unit=1)[7:],1)
 def test_out_of_range(self):
  with self.assertRaises(s.AcquisitionError):s.decode_response(self.packet(1010)[:7],self.packet(1010)[7:],1)
 def test_bad_fc(self):
  with self.assertRaises(s.AcquisitionError):s.decode_response(self.packet(fc=6)[:7],self.packet(fc=6)[7:],1)
 def test_read_request(self):
  sock=FakeSocket(self.packet());result=s.read_soc(connector=lambda *a:sock)
  self.assertEqual(result,75);self.assertEqual(sock.sent[7],4);self.assertEqual(sock.sent[-4:],struct.pack('>HH',30005,34));self.assertTrue(sock.closed)
 def test_short_response(self):
  with self.assertRaises(s.AcquisitionError):s.read_soc(connector=lambda *a:FakeSocket(self.packet()[:8]))
 def test_bounded(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(s.AcquisitionError):s.run(1801,2,pathlib.Path(d)/'x')
 def test_no_slot(self):self.assertEqual(s.main(['--execute-slot']),2)
 def test_append_only(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'log';s.append(p,{'a':1});s.append(p,{'a':2});self.assertEqual(len(p.read_text().splitlines()),2)
 def test_symlink(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'data';p.write_text('safe');link=Path(d)/'link';link.symlink_to(p)
   with self.assertRaises(s.AcquisitionError):s.append(link,{'a':3})
 def test_declares_soc_only(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'log';ticks=iter((0,0.1,0.2,0.3,1.1,1.2,1.3,2.1,2.2,2.3,3.1))
   result=s.run(2,1,p,reader=lambda:50,clock=lambda:next(ticks),sleeper=lambda n:None)
   self.assertFalse(result['grid_side_delivery_verified']);self.assertEqual(result['modbus_writes'],0)
   row=json.loads(p.read_text().splitlines()[0]);self.assertIsNone(row['battery_kw']);self.assertIsNone(row['grid_kw'])
 def test_no_write_functions(self):
  source=Path(s.__file__).read_text();self.assertNotIn('write_holding',source);self.assertNotIn('write_u32',source)
if __name__=='__main__':unittest.main()
