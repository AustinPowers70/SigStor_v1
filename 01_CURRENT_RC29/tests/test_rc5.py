import datetime as dt,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
import session_integration_rc5 as m
import rc5_preflight
UTC=dt.timezone.utc
class FakeClock:
 def __init__(self):self.n=0;self.t0=dt.datetime(2026,11,1,12,tzinfo=UTC)
 def utc(self):return self.t0+dt.timedelta(seconds=self.n)
 def tick(self):return self.n
 def sleep(self,n):self.n+=n
class Fake:
 simulation_only=True
 def __init__(self,fail=False):self.started=False;self.back=False;self.fail=fail
 def start(self,a,p):self.started=True
 def handback(self):self.back=True;return not self.fail

class RC5Tests(unittest.TestCase):
 def setUp(self):
  self.clock=FakeClock();self.fake=Fake();self.events=[]
  self.plan={'state':'QUALIFIED_SIMULATION_ONLY','dispatch_enabled':False,'source_fingerprint':'abc',
   'action':'GRID_CHARGE','start_utc':self.clock.utc().isoformat(),
   'end_utc':(self.clock.utc()+dt.timedelta(seconds=8)).isoformat(),'rated_kw':.5}
 def run_session(self,plan=None,source=None,telemetry=None,fake=None):
  c=self.clock
  return m.run_offline(plan=plan or self.plan,read_sources=source or (lambda:self.plan),
   read_telemetry=telemetry or (lambda:{'valid':True,'observed_utc':c.utc().isoformat(),
     'soc_pct':50,'battery_kw':.4,'reserve_pct':20}),simulator=fake or self.fake,
   utcnow=c.utc,monotonic=c.tick,sleep=c.sleep,audit=lambda *e:self.events.append(e))
 def test_complete(self):
  r=self.run_session();self.assertEqual(r['modbus_writes'],0);self.assertTrue(self.fake.back)
 def test_invalid_plan(self):
  with self.assertRaises(m.IntegrationError):self.run_session(plan=dict(self.plan,state='HOLD'))
 def test_real_adapter_rejected(self):
  class Real:pass
  with self.assertRaises(m.IntegrationError):self.run_session(fake=Real())
 def test_changed_snapshot_aborts_and_handback(self):
  def source():return dict(self.plan,source_fingerprint='changed') if self.clock.n else self.plan
  with self.assertRaises(m.IntegrationError):self.run_session(source=source)
  self.assertTrue(self.fake.back)
 def test_bad_telemetry_aborts(self):
  with self.assertRaises(m.IntegrationError):self.run_session(telemetry=lambda:{'valid':False})
  self.assertTrue(self.fake.back)
 def test_soc_ceiling(self):
  with self.assertRaises(m.IntegrationError):self.run_session(telemetry=lambda:{'valid':True,'observed_utc':self.clock.utc().isoformat(),'soc_pct':96,'battery_kw':.1,'reserve_pct':20})
  self.assertTrue(self.fake.back)
 def test_export_reserve(self):
  self.plan['action']='EXPORT'
  with self.assertRaises(m.IntegrationError):self.run_session(telemetry=lambda:{'valid':True,'observed_utc':self.clock.utc().isoformat(),'soc_pct':20,'battery_kw':-.65,'reserve_pct':20})
  self.assertTrue(self.fake.back)
 def test_handback_unverified(self):
  self.fake.fail=True
  with self.assertRaisesRegex(m.IntegrationError,'handback unverified'):self.run_session()
 def test_expired(self):
  self.plan['end_utc']=(self.clock.utc()-dt.timedelta(seconds=1)).isoformat()
  with self.assertRaisesRegex(m.IntegrationError,'expired'):self.run_session()
 def test_clock_jump(self):
  calls=[0]
  def utc():
   calls[0]+=1
   return self.clock.utc()+ (dt.timedelta(seconds=30) if calls[0]>4 else dt.timedelta())
  with self.assertRaises(m.IntegrationError):
   m.run_offline(plan=self.plan,read_sources=lambda:self.plan,read_telemetry=lambda:{'valid':True,'observed_utc':self.clock.utc().isoformat(),'soc_pct':50,'battery_kw':.4,'reserve_pct':20},simulator=self.fake,utcnow=utc,monotonic=self.clock.tick,sleep=self.clock.sleep,audit=lambda *x:None)
  self.assertTrue(self.fake.back)
 def test_cli_block(self):self.assertEqual(rc5_preflight.main(['--execute-slot']),2)
 def test_source_fingerprint_stable(self):
  self.assertEqual(m.source_fingerprint({'a':1},{},{},{}),m.source_fingerprint({'a':1},{},{},{}))
 def test_compiled_source_no_live_bridge(self):
  source=Path(m.__file__).read_text()
  self.assertNotIn('from supervised_charge import',source)
  self.assertNotIn('socket.create_connection',source)
if __name__=='__main__':unittest.main()
