import copy,sys,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
import rc13_gateway as g
import slot_supervisor as s

class OfflineTests(unittest.TestCase):
 def setUp(self):
  now=datetime(2026,11,1,17,35,tzinfo=timezone.utc)
  self.now=now;start=now-timedelta(minutes=5)
  self.d={'Bridge':{'TerminalDemandCommitmentKwh':3.0},'Candidate':{'Schema':'SIGENSTOR_RTM_V12_UNIFIED_ADVISORY','Status':'OPTIMAL_RESEARCH_CANDIDATE','SolverStatus':0,'SourceSnapshotUtc':now.isoformat(),'SoftReservePercent':15,'RequiredTerminalKwh':3.0,'Schedule':[{'StartUtc':start.isoformat(),'GridChargeKwh':0.05,'GridExportKwh':0.0}],'ForecastSlots':1,'ResearchOnly':True,'DispatchEnabled':False,'TradingApproved':False,'ProductionApproved':False},'Reconciliation':{'Qualification':'INDEPENDENT_MODEL_RECONCILED_ADVISORY_ONLY','LiveDispatchQualification':'NOT_APPROVED','OperatorExecutionAllowed':False,'ModbusCommandsIssued':0,'DispatchEnabled':False,'SourceSnapshotUtc':now.isoformat(),'SoftReservePercent':15,'ForecastSlots':1},'DispatchEnabled':False,'ResearchOnly':True}
  self.settings={'SoftReservePercent':15};self.authority={'requested':'MANUAL','dispatch_authorised':False,'remote_ems_verified_off':True}
 def test_charge_plan_read_only(self):
  p=s.plan(self.d,self.settings,self.authority,self.now)
  self.assertEqual(p['Decision'],'GRID_CHARGE');self.assertFalse(p['ExecutionEnabled']);self.assertEqual(p['ModbusWrites'],0);self.assertEqual(p['RemainingSeconds'],1500)
 def test_export_plan_read_only(self):
  self.d['Candidate']['Schedule'][0].update(GridChargeKwh=0,GridExportKwh=.05)
  self.assertEqual(s.plan(self.d,self.settings,self.authority,self.now)['Decision'],'EXPORT')
 def test_authority_fail_closed(self):
  self.authority['requested']='AUTO';self.assertEqual(s.plan(self.d,self.settings,self.authority,self.now)['Decision'],'HOLD_AUTHORITY_NOT_READY')
 def test_stale_snapshot_rejected(self):
  stale=(self.now-timedelta(minutes=11)).isoformat();self.d['Candidate']['SourceSnapshotUtc']=stale;self.d['Reconciliation']['SourceSnapshotUtc']=stale
  with self.assertRaises(ValueError):s.plan(self.d,self.settings,self.authority,self.now)
 def test_reserve_mismatch_rejected(self):
  self.settings['SoftReservePercent']=20
  with self.assertRaises(ValueError):s.plan(self.d,self.settings,self.authority,self.now)
 def test_conflicting_commands_rejected(self):
  self.d['Candidate']['Schedule'][0]['GridExportKwh']=.1
  with self.assertRaises(ValueError):s.plan(self.d,self.settings,self.authority,self.now)
 def test_outside_window(self):
  t=self.now+timedelta(minutes=26);self.d['Candidate']['SourceSnapshotUtc']=t.isoformat();self.d['Reconciliation']['SourceSnapshotUtc']=t.isoformat()
  self.assertEqual(s.plan(self.d,self.settings,self.authority,t)['Decision'],'HOLD_OUTSIDE_HORIZON')
 def test_incapable_energy_marked(self):
  self.d['Candidate']['Schedule'][0]['GridChargeKwh']=1.0
  self.assertFalse(s.plan(self.d,self.settings,self.authority,self.now)['CanDeliverWithinRemainingSlot'])
 def test_execution_entrypoint_blocked(self):
  self.assertEqual(s.main(['--execute-slot']),2)
 def test_no_40034_write_in_source(self):
  for f in (Path(__file__).resolve().parents[1]/'controller').glob('*.py'):
   data=f.read_text()
   self.assertNotIn('write(40034',data);self.assertNotIn('write_u32(40034',data)
if __name__=='__main__':unittest.main()
