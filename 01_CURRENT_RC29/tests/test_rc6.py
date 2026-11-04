import datetime as dt, json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
import evidence_rc6 as e
class RC6Tests(unittest.TestCase):
 def setUp(self):
  self.now='2026-11-01T18:00:00+00:00'
  self.sample={'valid':True,'observed_utc':self.now,'soc_pct':64,'battery_kw':-.65}
 def test_valid_battery_port(self):
  v=e.classify(self.sample,self.now);self.assertEqual(v['energy_boundary'],'BATTERY_PORT_ONLY');self.assertFalse(v['grid_side_battery_energy_verified'])
 def test_stale_rejected(self):
  with self.assertRaises(e.EvidenceError):e.classify(self.sample,'2026-11-01T18:01:00+00:00')
 def test_future_rejected(self):
  with self.assertRaises(e.EvidenceError):e.classify(self.sample,'2026-11-01T17:59:00+00:00')
 def test_timezone_required(self):
  with self.assertRaises(e.EvidenceError):e.classify(dict(self.sample,observed_utc='2026-11-01T18:00:00'),self.now)
 def test_invalid_flag(self):
  with self.assertRaises(e.EvidenceError):e.classify(dict(self.sample,valid=False),self.now)
 def test_nan_rejected(self):
  with self.assertRaises(e.EvidenceError):e.classify(dict(self.sample,battery_kw=float('nan')),self.now)
 def test_bad_soc(self):
  with self.assertRaises(e.EvidenceError):e.classify(dict(self.sample,soc_pct=101),self.now)
 def test_append_only(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'audit.jsonl';v=e.classify(self.sample,self.now)
   e.append_jsonl(p,v);e.append_jsonl(p,v)
   self.assertEqual(len(p.read_text().splitlines()),2)
   self.assertTrue(all(x['modbus_writes']==0 for x in map(json.loads,p.read_text().splitlines())))
 def test_symlink_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'target';p.write_text('original');link=Path(d)/'link';link.symlink_to(p)
   with self.assertRaises(e.EvidenceError):e.append_jsonl(link,{})
   self.assertEqual(p.read_text(),'original')
 def test_live_entry_blocked(self):self.assertEqual(e.main(['--execute-slot']),2)
 def test_no_network_actuator(self):
  s=Path(e.__file__).read_text();self.assertNotIn('socket.create_connection',s);self.assertNotIn('supervised_charge import',s)
if __name__=='__main__':unittest.main()
