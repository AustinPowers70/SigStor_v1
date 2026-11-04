import sys,unittest,tempfile,json,types,inspect
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'controller'))
import commissioning_permit_rc28 as permit
import attended_commissioning_rc28 as parent
import commissioning_controller_rc28 as child
import controller,supervised_export
class RC28(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();p=Path(self.temp.name)
  self.a=p/'authority.json';self.s=p/'reserve.json';self.s.write_text(json.dumps({'SoftReservePercent':20}))
  self.a.write_text(json.dumps({'requested':'MANUAL','dispatch_authorised':False,'remote_ems_verified_off':True}))
  self.pf=lambda:{'plant_handback_verified':True,'soc_pct':60}
  self.panel=lambda *args:types.SimpleNamespace(returncode=0,stdout='active')
 def tearDown(self):self.temp.cleanup()
 def q(self,action):return permit.qualify(action,authority_path=self.a,reserve_path=self.s,preflight=self.pf,panel=self.panel)
 def test_manual_charge_no_rc13_required(self):
  q,reserve=self.q('GRID_CHARGE');self.assertTrue(q['CommissioningOnly']);self.assertEqual(reserve,20)
 def test_manual_export(self):self.assertEqual(self.q('EXPORT')[0]['Decision'],'EXPORT')
 def test_dispatch_authority_rejected(self):
  self.a.write_text(json.dumps({'requested':'MANUAL','dispatch_authorised':True,'remote_ems_verified_off':True}))
  with self.assertRaises(permit.PermitHold):self.q('GRID_CHARGE')
 def test_remote_ems_authority_rejected(self):
  self.a.write_text(json.dumps({'requested':'MANUAL','dispatch_authorised':False,'remote_ems_verified_off':False}))
  with self.assertRaises(permit.PermitHold):self.q('GRID_CHARGE')
 def test_reserve_rejected(self):
  self.s.write_text(json.dumps({'SoftReservePercent':105}))
  with self.assertRaises(permit.PermitHold):self.q('GRID_CHARGE')
 def test_plant_not_handed_back(self):
  self.pf=lambda:{'plant_handback_verified':False,'soc_pct':60}
  with self.assertRaises(permit.PermitHold):self.q('GRID_CHARGE')
 def test_charge_soc_guard(self):
  self.pf=lambda:{'plant_handback_verified':True,'soc_pct':96}
  with self.assertRaises(permit.PermitHold):self.q('GRID_CHARGE')
 def test_export_soc_guard(self):
  self.pf=lambda:{'plant_handback_verified':True,'soc_pct':21}
  with self.assertRaises(permit.PermitHold):self.q('EXPORT')
 def test_no_direct_dispatch_without_approval(self):
  with self.assertRaisesRegex(Exception,'operator-ack'):
   from attended_commissioning_rc27 import orchestrate
   orchestrate('GRID_CHARGE',False,check=lambda a:{'source_slot':'MANUAL_COMMISSIONING_30S','reserve_percent':20})
 def test_active_phase_avoids_handback_during_live_pulse(self):
  self.pf=lambda:(_ for _ in ()).throw(RuntimeError('preflight must not run while active'))
  q,_=permit.qualify('GRID_CHARGE','ACTIVE',authority_path=self.a,reserve_path=self.s,preflight=self.pf,panel=self.panel)
  self.assertEqual(q['Decision'],'GRID_CHARGE')
 def test_existing_rc13_qualify_default_unchanged(self):
  self.assertEqual(inspect.signature(controller.execute).parameters['qualification'].default,None)
  self.assertEqual(inspect.signature(supervised_export.perform_export).parameters['qualification'].default,None)
 def test_no_40034(self):
  for f in ('commissioning_controller_rc28.py','commissioning_permit_rc28.py','attended_commissioning_rc28.py'):
   txt=(Path(__file__).resolve().parent.parent/'controller'/f).read_text()
   self.assertNotIn('write(40034',txt);self.assertNotIn('write_u32(40034',txt)
