import datetime as dt, importlib.util, pathlib, unittest, tempfile, json
p=pathlib.Path(__file__).resolve().parents[1]/'controller'/'commissioning_gate_rc13.py'
s=importlib.util.spec_from_file_location('gate13',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
BASE=dt.datetime(2026,11,1,10,tzinfo=dt.timezone.utc)
def stamp(n):return (BASE+dt.timedelta(seconds=n)).isoformat()
def fixture():
 plan=dict(action='GRID_CHARGE',autonomous_dispatch=False,operator_approved=True,single_writer_verified=True,
 authority_isolated=True,rc13_unchanged=True,discharge_limit_untouched=True,slot_qualification_continuous=True,
 remote_ems_verified_off_before=True,handback_remote_ems_off=True,handback_self_consumption=True,
 operator_attended=True,rated_kw=.5,start_utc=stamp(0),end_utc=stamp(20))
 samples=[dict(observed_utc=stamp(n),valid=True,soc_pct=65,battery_kw=-.5,grid_kw=.6) for n in range(0,21,4)]
 events=[{'event':'START_ATTEMPTED'},{'event':'HANDBACK_VERIFIED'}]
 return plan,samples,events
class RC13Tests(unittest.TestCase):
 def test_review_not_release(self):
  r=m.evaluate(*fixture());self.assertTrue(r['review_ready']);self.assertFalse(r['release_authorised']);self.assertFalse(r['grid_side_battery_delivery_verified'])
 def test_no_auto(self):
  p,s,e=fixture();p['autonomous_dispatch']=True;self.assertIn('AUTONOMOUS_DISPATCH_NOT_DISABLED',m.evaluate(p,s,e)['issues'])
 def test_operator(self):
  p,s,e=fixture();p['operator_approved']=False;self.assertIn('MANUAL_APPROVAL_ABSENT',m.evaluate(p,s,e)['issues'])
 def test_lock(self):
  p,s,e=fixture();p['single_writer_verified']=False;self.assertIn('SINGLE_WRITER_NOT_VERIFIED',m.evaluate(p,s,e)['issues'])
 def test_panel(self):
  p,s,e=fixture();p['authority_isolated']=False;self.assertIn('AUTHORITY_NOT_ISOLATED',m.evaluate(p,s,e)['issues'])
 def test_handback(self):
  p,s,e=fixture();p['handback_remote_ems_off']=False;self.assertFalse(m.evaluate(p,s,e)['review_ready'])
 def test_pcs_export(self):
  p,s,e=fixture();p.update(action='EXPORT',rated_kw=.65,soft_reserve_pct=20);self.assertIn('PCS_REQUEST_NOT_VERIFIED_ZERO',m.evaluate(p,s,e)['issues'])
 def test_power(self):
  p,s,e=fixture();p['rated_kw']=.501;self.assertIn('POWER_LIMIT_EXCEEDED',m.evaluate(p,s,e)['issues'])
 def test_gap(self):
  p,s,e=fixture();s.pop(2);self.assertIn('DUPLICATE_OR_GAPPED_SAMPLES',m.evaluate(p,s,e)['issues'])
 def test_boundary(self):
  p,s,e=fixture();s=s[2:];self.assertIn('BOUNDARY_COVERAGE_UNVERIFIED',m.evaluate(p,s,e)['issues'])
 def test_soc_ceiling(self):
  p,s,e=fixture();s[1]['soc_pct']=95;self.assertIn('SOC_CEILING_VIOLATED',m.evaluate(p,s,e)['issues'])
 def test_reserve(self):
  p,s,e=fixture();p.update(action='EXPORT',rated_kw=.65,soft_reserve_pct=66,handback_pcs_zero=True);self.assertIn('RESERVE_VIOLATED',m.evaluate(p,s,e)['issues'])
 def test_invalid_sample(self):
  p,s,e=fixture();s[1]['grid_kw']=float('nan');self.assertIn('INVALID_IN_SESSION_SAMPLE',m.evaluate(p,s,e)['issues'])
 def test_critical(self):
  p,s,e=fixture();e.append({'event':'CRITICAL_HANDBACK_UNVERIFIED'});self.assertIn('CRITICAL_EVENT_PRESENT',m.evaluate(p,s,e)['issues'])
 def test_blocked_cli(self):self.assertEqual(m.main(['--evidence','/nonexistent','--execute-slot']),2)
 def test_no_write_interface(self):
  text=p.read_text();self.assertNotIn('write_u32(',text);self.assertNotIn('write_holding(',text)
