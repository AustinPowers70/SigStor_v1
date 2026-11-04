import sys,unittest,datetime as dt,types
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'controller'))
import attended_commissioning_rc27 as m

class TestRC27(unittest.TestCase):
 def test_readonly_no_approval(self):
  with self.assertRaisesRegex(m.CommissioningHold,'operator-ack'):
   m.orchestrate('GRID_CHARGE',False,check=lambda a:{'source_slot':'x','reserve_percent':20})
 def test_consent_no_tty(self):
  with self.assertRaisesRegex(m.CommissioningHold,'TTY'):
   m.local_consent('EXPORT',is_tty=False)
 def test_consent_exact(self):
  with self.assertRaisesRegex(m.CommissioningHold,'did not authorise'):
   m.local_consent('GRID_CHARGE',input_fn=lambda _: 'yes',is_tty=True)
  self.assertTrue(m.local_consent('EXPORT',input_fn=lambda _: 'AUTHORISE EXPORT 30 SECONDS',is_tty=True))
 def test_action_allowlist(self):
  self.assertEqual(set(m.ACTIONS),{'GRID_CHARGE','EXPORT'})
 def test_observation_record(self):
  rows=[]
  obs=m.Observation('/simulated',read=lambda:{'soc_pct':60,'battery_kw':-1,'grid_kw':0,'pv_kw':0,'home_kw':1},writer=lambda p,r:rows.append(r))
  obs.stop=types.SimpleNamespace(is_set=lambda:len(rows)>=1,wait=lambda n:None)
  obs.run()
  self.assertEqual(obs.counts['BEFORE'],1)
  self.assertTrue(rows[0]['valid'])
  self.assertEqual(rows[0]['modbus_writes_by_observer'],0)
 def test_observation_bad(self):
  rows=[]
  obs=m.Observation('/simulated',read=lambda:{'soc_pct':float('nan'),'battery_kw':-1,'grid_kw':0,'pv_kw':0,'home_kw':1},writer=lambda p,r:rows.append(r))
  obs.stop=types.SimpleNamespace(is_set=lambda:len(rows)>=1,wait=lambda n:None)
  obs.run()
  self.assertEqual(obs.invalid,1)
 def test_check_invalid_action(self):
  with self.assertRaisesRegex(m.CommissioningHold,'unknown action'):
   m.eligibility('WRONG')
 def test_execution_aborts_on_qual_change_before_latch(self):
  calls=[]
  def check(a):
   calls.append(a);return {'source_slot':str(len(calls)),'reserve_percent':20}
  with self.assertRaisesRegex(m.CommissioningHold,'qualification changed'):
   m.orchestrate('GRID_CHARGE',True,check=check,consent=lambda a:True,latch_factory=lambda p:self.fail('latch should not be touched'))

class TestRC27Transaction(unittest.TestCase):
 def _run(self,child_exit):
  class FakeLatch:
   def __init__(self):self.armed=False;self.cleared=False
   def arm(self,s):self.armed=True
   def clear_after_verified_completion(self,s,verified):self.cleared=True
  class FakeObserver:
   def __init__(self):
    self.counts={'BEFORE':2,'DURING':5,'AFTER':2};self.invalid=0;self.error=None
    self.stop=types.SimpleNamespace(set=lambda:None)
   def run(self):pass
   def event(self,*args,**kwargs):pass
  class FakeChild:
   returncode=child_exit
   def communicate(self,timeout):return ('test',None)
  state={}
  def factory(path):
   state['latch']=FakeLatch();return state['latch']
  def observer(path):return FakeObserver()
  result=m.orchestrate('GRID_CHARGE',True,check=lambda action:{'source_slot':'x','reserve_percent':20},
   consent=lambda action:True,popen=lambda *a,**kw:FakeChild(),observer_factory=observer,
   preflight=lambda:{'plant_handback_verified':True},latch_factory=factory,
   sleep=lambda secs:None,panel_check=lambda:types.SimpleNamespace(returncode=0,stdout='active'))
  return result,state['latch']
 def test_success_clears_latch_only_after_proof(self):
  result,latch=self._run(0)
  self.assertEqual(result['status'],'SUPERVISED_PILOT_HANDBACK_CONFIRMED')
  self.assertTrue(latch.armed and latch.cleared)
 def test_child_error_retains_latch(self):
  result,latch=self._run(2)
  self.assertEqual(result['status'],'HOLD_RECOVERY_REQUIRED')
  self.assertTrue(latch.armed)
  self.assertFalse(latch.cleared)
