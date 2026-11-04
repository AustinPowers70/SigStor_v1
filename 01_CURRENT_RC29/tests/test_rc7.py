import datetime as dt,sys,tempfile,sqlite3,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
import commissioning_evidence as e
class EvidenceTests(unittest.TestCase):
 def setUp(self):
  self.start='2026-11-01T18:00:00Z';self.end='2026-11-01T18:00:20Z'
  self.rows=[{'timestamp_utc':f'2026-11-01T18:00:{s:02d}Z','battery_kw':-.65,'grid_kw':-.35,'soc_pct':60} for s in (0,5,10,15,20)]
 def test_dense_export(self):
  v=e.assess(self.rows,self.start,self.end,'EXPORT');self.assertTrue(v['commissioning_evidence_ready']);self.assertFalse(v['battery_grid_side_delivery_verified'])
 def test_wrong_direction(self):self.assertFalse(e.assess(self.rows,self.start,self.end,'GRID_CHARGE')['commissioning_evidence_ready'])
 def test_gap(self):self.assertFalse(e.assess([self.rows[0],self.rows[-1]],self.start,self.end,'EXPORT')['dense_samples_verified'])
 def test_zero_actual_samples(self):self.assertEqual(e.assess([],self.start,self.end,'EXPORT')['qualification'],'INSUFFICIENT_IN_SESSION_EVIDENCE')
 def test_boundary_not_interpolated(self):self.assertFalse(e.assess(self.rows[1:],self.start,self.end,'EXPORT',max_gap_s=4)['edge_observed'])
 def test_duplicate(self):self.assertFalse(e.assess(self.rows+[self.rows[2]],self.start,self.end,'EXPORT')['dense_samples_verified'])
 def test_invalid(self):self.assertFalse(e.assess(self.rows+[dict(self.rows[2],soc_pct=float('nan'))],self.start,self.end,'EXPORT')['dense_samples_verified'])
 def test_naive_time(self):
  with self.assertRaises(e.EvidenceQualityError):e.assess([],self.start,self.end.replace('Z',''),'EXPORT')
 def test_no_allocation_claim(self):self.assertFalse(e.assess(self.rows,self.start,self.end,'EXPORT')['meter_battery_allocation_verified'])
 def test_sqlite_read_only(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'in.sqlite'
   with sqlite3.connect(path) as c:
    c.execute('CREATE TABLE telemetry(timestamp_utc TEXT,battery_kw REAL,grid_kw REAL,soc_pct REAL)')
    for r in self.rows:c.execute('INSERT INTO telemetry VALUES (?,?,?,?)',tuple(r.values()))
   self.assertEqual(len(e.from_sqlite(path,e.stamp(self.start),e.stamp(self.end))),5)
 def test_symlink_denied(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'db';p.write_bytes(b'x');ln=Path(d)/'ln';ln.symlink_to(p)
   with self.assertRaises(e.EvidenceQualityError):e.from_sqlite(ln,e.stamp(self.start),e.stamp(self.end))
 def test_no_modbus(self):self.assertNotIn('pymodbus',Path(e.__file__).read_text())
if __name__=='__main__':unittest.main()
