import sys,unittest,tempfile,sqlite3,datetime as dt,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
import integrated_preview as x
from test_phase3b_rc1 import OfflineTests
class IntegratedTests(OfflineTests):
 def r5(self):
  start=self.d['Candidate']['Schedule'][0]['StartUtc']; end=(dt.datetime.fromisoformat(start)+dt.timedelta(minutes=30)).isoformat()
  return {'schema':'SIGEN_PHASE3A_VERIFIED_ENVELOPE_R5','contract_verified':True,'contract':'GRID_SIDE_CHARGE_AND_EXPORT_KWH','execution_authorised':False,'autonomous_dispatch':False,'source_snapshot_utc':self.now.isoformat(),'source_sha256':'pinned-test-fixture','slots':[{'action':'GRID_CHARGE','grid_side_kwh':.05,'average_grid_side_kw':.1,'start_utc':start,'end_utc':end}]}
 def test_integrated_match(self):
  result=x.evaluate(self.d,self.settings,self.authority,self.r5(),None,self.now)
  self.assertEqual(result['readiness'],'PREVIEW_MATCHED_NO_EXECUTION');self.assertFalse(result['execution_enabled'])
 def test_integrated_mismatch(self):
  r=self.r5();r['slots'][0]['grid_side_kwh']=.1;r['slots'][0]['average_grid_side_kw']=.2
  self.assertEqual(x.evaluate(self.d,self.settings,self.authority,r,None,self.now)['readiness'],'HOLD_R5_RC13_MISMATCH')
 def test_missing_r5_fail_closed(self):
  self.assertEqual(x.evaluate(self.d,self.settings,self.authority,None,None,self.now)['readiness'],'HOLD_MISSING_R5_CONTRACT')
 def test_integrated_execution_blocked(self):self.assertEqual(x.main(['--execute-slot']),2)
 def test_r6_invalid_grid_side_power(self):
  m=x.module(x.R6,'test_r6');r=self.r5();r['slots'][0]['average_grid_side_kw']=5
  with self.assertRaises(ValueError):m.build(r,self.now)
 def test_r10_zero_actual_samples_not_measured(self):
  m=x.module(x.R10,'test_r10');start=self.now-dt.timedelta(seconds=120)
  with tempfile.TemporaryDirectory() as td:
   db=Path(td)/'samples.sqlite';con=sqlite3.connect(db)
   con.execute('CREATE TABLE telemetry (timestamp_utc TEXT,battery_kw REAL,grid_kw REAL,soc_pct REAL)');con.commit();con.close()
   e=m.evaluate(db,start,self.now,'GRID_CHARGE',.02,self.now)
   self.assertEqual(e['measurement_state'],'INCOMPLETE_BATTERY_PORT_EVIDENCE');self.assertIsNone(e['grid_side_delivered_kwh'])
 def test_atomic_output(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'out.json';x.write_atomic(p,{'modbus_writes':0});self.assertEqual(__import__('json').loads(p.read_text())['modbus_writes'],0)
 def test_r10_coverage_gap(self):
  m=x.module(x.R10,'test_r10_2');a=self.now-dt.timedelta(seconds=600)
  p=[(a,.5),(a+dt.timedelta(seconds=605),.5)]
  self.assertEqual(m.segments(p,a,self.now)['coverage_pct'],0)
if __name__=='__main__':unittest.main()
