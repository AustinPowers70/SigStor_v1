import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'controller'))
import authority_transaction_rc11 as a
PLAN={'state':'QUALIFIED_SIMULATION_ONLY','dispatch_enabled':False,'action':'GRID_CHARGE','start_utc':'a','end_utc':'b','source_fingerprint':'xyz','rated_kw':0.5}
class Lock:
 simulation_only=True
 def __init__(self,ok=True):self.ok=ok;self.released=False
 def acquire_nonblocking(self):return self.ok
 def release(self):self.released=True
class Panel:
 simulation_only=True
 def __init__(self):self.active=True;self.stop_calls=0;self.start_calls=0
 def is_active(self):return self.active
 def stop(self):self.stop_calls+=1;self.active=False
 def start(self):self.start_calls+=1;self.active=True
class Act:
 simulation_only=True
 def __init__(self,handback=True,fail_start=False):self.handback_ok=handback;self.fail_start=fail_start;self.calls=[]
 def start(self,*x):
  self.calls.append('start')
  if self.fail_start:raise IOError('uncertain start')
 def handback(self):self.calls.append('handback');return self.handback_ok
class Tests(unittest.TestCase):
 def run_case(self,**kw):
  lock=kw.get('lock',Lock());panel=kw.get('panel',Panel());act=kw.get('act',Act());events=[]
  f=kw.get('qualify',lambda:dict(PLAN))
  result=a.rehearsal(plan=kw.get('plan',PLAN),lock=lock,panel=panel,actuator=act,audit=lambda ev,d:events.append(ev),qualify=f)
  return result,lock,panel,act,events
 def test_success(self):
  r,l,p,x,e=self.run_case();self.assertTrue(r.handback_verified);self.assertTrue(p.active);self.assertTrue(l.released)
 def test_lock_occupied(self):
  with self.assertRaisesRegex(a.AuthorityError,'lock occupied'):self.run_case(lock=Lock(False))
 def test_changed_qualification(self):
  with self.assertRaisesRegex(a.AuthorityError,'qualification changed'):self.run_case(qualify=lambda:{**PLAN,'action':'EXPORT'})
 def test_handback_uncertain_blocks_restart(self):
  p=Panel();x=Act(False)
  with self.assertRaisesRegex(a.AuthorityError,'handback unverified'):self.run_case(panel=p,act=x)
  self.assertEqual(p.start_calls,0);self.assertEqual(x.calls,['start','handback'])
 def test_uncertain_start_still_handback(self):
  p=Panel();x=Act(True,True)
  with self.assertRaisesRegex(a.AuthorityError,'uncertain start'):self.run_case(panel=p,act=x)
  self.assertEqual(x.calls,['start','handback']);self.assertTrue(p.active)
 def test_real_actuator_rejected(self):
  x=Act();x.simulation_only=False
  with self.assertRaisesRegex(a.AuthorityError,'prohibited'):self.run_case(act=x)
 def test_real_panel_rejected(self):
  p=Panel();p.simulation_only=False
  with self.assertRaisesRegex(a.AuthorityError,'prohibited'):self.run_case(panel=p)
 def test_real_lock_rejected(self):
  l=Lock();l.simulation_only=False
  with self.assertRaisesRegex(a.AuthorityError,'prohibited'):self.run_case(lock=l)
 def test_invalid_plan(self):
  with self.assertRaisesRegex(a.AuthorityError,'plan required'):self.run_case(plan={**PLAN,'dispatch_enabled':True})
 def test_no_modbus_import(self):
  s=pathlib.Path(a.__file__).read_text();self.assertNotIn('import socket',s);self.assertNotIn('subprocess',s)
 def test_cli_block(self):self.assertEqual(a.main(),2)
