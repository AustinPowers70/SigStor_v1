import pathlib,sys,unittest,datetime as dt
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'controller'))
import supervised_rehearsal_rc12 as m
UTC=dt.timezone.utc
class T:
 def __init__(self):self.n=0.;self.base=dt.datetime(2026,11,1,18,tzinfo=UTC);self.jump=0
 def clock(self):return self.n
 def now(self):return self.base+dt.timedelta(seconds=self.n+self.jump)
 def sleep(self,n):self.n+=n
class Lock:
 simulation_only=True
 def __init__(self,ok=True):self.ok=ok;self.released=False
 def acquire_nonblocking(self):return self.ok
 def release(self):self.released=True
class Panel:
 simulation_only=True
 def __init__(self):self.active=True;self.starts=0
 def is_active(self):return self.active
 def stop(self):self.active=False
 def start(self):self.active=True;self.starts+=1
class Act:
 simulation_only=True
 def __init__(self,back=True,fail=False):self.back=back;self.fail=fail;self.calls=[]
 def start(self,*args):
  self.calls.append('start')
  if self.fail:raise RuntimeError('uncertain start')
 def handback(self):self.calls.append('handback');return self.back
class Tests(unittest.TestCase):
 def make(self,action='GRID_CHARGE',**changes):
  t=T();plan=dict(state='QUALIFIED_SIMULATION_ONLY',dispatch_enabled=False,action=action,
    start_utc=t.now().isoformat(),end_utc=(t.now()+dt.timedelta(minutes=30)).isoformat(),source_fingerprint='fixed',rated_kw=0.5)
  p=Panel();l=Lock();a=Act();events=[]
  def qualify(now):return dict(plan)
  def sample():return {'valid':True,'observed_utc':t.now().isoformat(),'soc_pct':70,
   'battery_kw':-.5,'grid_kw':.6,'reserve_pct':20}
  kw=dict(plan=plan,lock=l,panel=p,actuator=a,qualify=qualify,sample=sample,record=events.append,
          utcnow=t.now,clock=t.clock,sleep=t.sleep,duration_cap=5)
  kw.update(changes);return kw,t,p,l,a,events
 def test_success(self):
  k,t,p,l,a,e=self.make();r=m.run(**k);self.assertEqual(r['modbus_writes'],0);self.assertTrue(p.active);self.assertTrue(l.released);self.assertEqual(a.calls,['start','handback']);self.assertGreaterEqual(r['samples'],2)
 def test_source_change(self):
  k,t,p,l,a,e=self.make();k['qualify']=lambda now:{**k['plan'],'source_fingerprint':'changed'}
  with self.assertRaisesRegex(m.RehearsalError,'qualification'):m.run(**k)
  self.assertEqual(a.calls,[]);self.assertTrue(p.active)
 def test_stale(self):
  k,t,p,l,a,e=self.make();k['sample']=lambda:{'valid':True,'observed_utc':(t.now()-dt.timedelta(seconds=50)).isoformat(),'soc_pct':70,'battery_kw':1,'grid_kw':1,'reserve_pct':20}
  with self.assertRaisesRegex(m.RehearsalError,'stale'):m.run(**k)
  self.assertEqual(a.calls,['start','handback'])
 def test_reserve(self):
  k,t,p,l,a,e=self.make('EXPORT');k['sample']=lambda:{'valid':True,'observed_utc':t.now().isoformat(),'soc_pct':20,'battery_kw':.5,'grid_kw':-.4,'reserve_pct':20}
  with self.assertRaisesRegex(m.RehearsalError,'reserve'):m.run(**k)
  self.assertEqual(a.calls,['start','handback'])
 def test_ceiling(self):
  k,t,p,l,a,e=self.make();k['sample']=lambda:{'valid':True,'observed_utc':t.now().isoformat(),'soc_pct':95,'battery_kw':-.5,'grid_kw':.5,'reserve_pct':20}
  with self.assertRaisesRegex(m.RehearsalError,'ceiling'):m.run(**k)
 def test_uncertain_start_handback(self):
  k,t,p,l,a,e=self.make();a.fail=True
  with self.assertRaisesRegex(m.RehearsalError,'uncertain start'):m.run(**k)
  self.assertEqual(a.calls,['start','handback']);self.assertTrue(p.active)
 def test_handback_unverified_withholds_panel(self):
  k,t,p,l,a,e=self.make();a.back=False
  with self.assertRaisesRegex(m.RehearsalError,'handback unverified'):m.run(**k)
  self.assertFalse(p.active);self.assertTrue(l.released)
 def test_lock_occupied(self):
  k,t,p,l,a,e=self.make();l.ok=False
  with self.assertRaisesRegex(m.RehearsalError,'lock occupied'):m.run(**k)
  self.assertEqual(a.calls,[])
 def test_real_adapter_rejected(self):
  k,t,p,l,a,e=self.make();a.simulation_only=False
  with self.assertRaisesRegex(m.RehearsalError,'prohibited'):m.run(**k)
 def test_invalid_sample(self):
  k,t,p,l,a,e=self.make();k['sample']=lambda:{'valid':False}
  with self.assertRaisesRegex(m.RehearsalError,'invalid telemetry'):m.run(**k)
 def test_clock_jump(self):
  k,t,p,l,a,e=self.make();old=t.sleep
  def jump(n):old(n);t.jump=10
  k['sleep']=jump
  with self.assertRaisesRegex(m.RehearsalError,'clock discontinuity'):m.run(**k)
 def test_no_live_entry(self):self.assertEqual(m.main(),2)
 def test_no_control_interfaces(self):
  s=pathlib.Path(m.__file__).read_text();self.assertNotIn('import socket',s);self.assertNotIn('subprocess',s);self.assertNotIn('write_holding',s)
