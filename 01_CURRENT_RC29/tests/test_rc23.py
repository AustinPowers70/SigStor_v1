import unittest,sys,tempfile,pathlib,datetime as dt
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'controller'))
from attended_pilot_rc23 import PilotPermit,PilotHold,PilotCritical,run_injected,main
from recovery_attestation_rc22 import AttestedRecoveryLatch,RecoveryRequired
import test_rc20

class SimClock:
 def __init__(self):self.n=0;self.wall=dt.datetime(2026,11,4,19,0,tzinfo=dt.timezone.utc)
 def monotonic(self):return self.n
 def utcnow(self):return self.wall+dt.timedelta(seconds=self.n)
 def sleep(self,n):self.n+=n
class Lock:
 def __init__(self,allow=True):self.allow=allow;self.held=False
 def acquire_nonblocking(self):self.held=self.allow;return self.held
 def release(self):self.held=False
class Panel:
 def __init__(self):self.active=True
 def is_active(self):return self.active
 def stop(self):self.active=False
 def start(self):self.active=True
class Plant:
 simulation_only=True
 def __init__(self):self.register={40029:0,40031:2,40032:0,40001:0};self.writes=[];self.closed=False;self.fail_handback=False
 def read_holding(self,k):return self.register[k]
 def call(self,fc,payload):
  if self.fail_handback:return b'\x04\x00\x00\x00\x01'
  return b'\x04'+self.register[40001].to_bytes(4,'big')
 def write(self,k,v):self.writes.append((k,v));self.register[k]=v
 def write_u32(self,k,v):self.writes.append((k,v));self.register[k]=v
 def close(self):self.closed=True
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=pathlib.Path(self.tmp.name)/'latch';self.clock=SimClock()
  self.plant=Plant();self.lock=Lock();self.panel=Panel();self.events=[];self.present=lambda:True;self.qual=lambda p,t:True
  self.permit=PilotPermit('operator-rc23','GRID_CHARGE',self.clock.utcnow()+dt.timedelta(seconds=50),True,True,True,20.)
 def tearDown(self):self.tmp.cleanup()
 def runpilot(self,**overrides):
  args=dict(permit=self.permit,plant=self.plant,lock=self.lock,panel=self.panel,latch_path=self.path,
       presence=self.present,qualify=self.qual,sample=lambda:{'valid':True,'observed_utc':self.clock.utcnow(),
       'soc_pct':50.,'battery_kw':-0.5,'grid_kw':0.6},
       audit=lambda e,d:self.events.append((e,d)),utcnow=self.clock.utcnow,
       monotonic=self.clock.monotonic,sleep=self.clock.sleep)
  args.update(overrides);return run_injected(**args)
 def test_simulated_charge(self):
  x=self.runpilot();self.assertEqual(x['samples'],15);self.assertFalse(self.path.exists());self.assertTrue(self.panel.active)
  self.assertEqual(self.plant.register[40029],0);self.assertEqual(self.plant.register[40031],2)
 def test_simulated_export(self):
  self.permit=PilotPermit('operator-rc23','EXPORT',self.clock.utcnow()+dt.timedelta(seconds=50),True,True,True,20.)
  self.runpilot();self.assertIn((40001,650),self.plant.writes);self.assertEqual(self.plant.register[40001],0)
 def test_no_reserved_register_write(self):
  self.runpilot();self.assertFalse(any(k==40034 for k,v in self.plant.writes))
 def test_no_unbounded_duration(self):
  with self.assertRaises(PilotHold):self.runpilot(duration=120)
  self.assertFalse(self.plant.writes)
 def test_missing_operator_ack(self):
  self.permit=PilotPermit('operator-rc23','EXPORT',self.clock.utcnow()+dt.timedelta(seconds=50),False,True,True,20.)
  with self.assertRaises(PilotHold):self.runpilot()
  self.assertFalse(self.plant.writes)
 def test_expired_permit(self):
  self.permit=PilotPermit('operator-rc23','EXPORT',self.clock.utcnow()-dt.timedelta(seconds=1),True,True,True,20.)
  with self.assertRaises(PilotHold):self.runpilot()
 def test_lock_denied(self):
  self.lock.allow=False
  with self.assertRaises(PilotHold):self.runpilot()
  self.assertFalse(self.plant.writes)
 def test_preflight_qualification_denied(self):
  with self.assertRaises(PilotHold):self.runpilot(qualify=lambda p,t:False)
  self.assertFalse(self.plant.writes)
 def test_preflight_presence_denied(self):
  with self.assertRaises(PilotHold):self.runpilot(presence=lambda:False)
  self.assertFalse(self.plant.writes)
 def test_presence_loss_handback(self):
  with self.assertRaises(PilotHold):self.runpilot(presence=lambda:self.clock.n<6)
  self.assertEqual(self.plant.register[40029],0);self.assertTrue(self.panel.active)
 def test_soc_ceiling(self):
  with self.assertRaises(PilotHold):self.runpilot(sample=lambda:{'valid':True,'observed_utc':self.clock.utcnow(),'soc_pct':95.,'battery_kw':0.,'grid_kw':0.})
  self.assertEqual(self.plant.register[40029],0)
 def test_reserve(self):
  self.permit=PilotPermit('operator-rc23','EXPORT',self.clock.utcnow()+dt.timedelta(seconds=50),True,True,True,20.)
  with self.assertRaises(PilotHold):self.runpilot(sample=lambda:{'valid':True,'observed_utc':self.clock.utcnow(),'soc_pct':20.,'battery_kw':0.,'grid_kw':0.})
 def test_unverified_handback_retains_latch(self):
  self.plant.fail_handback=True
  with self.assertRaises(PilotCritical):self.runpilot()
  self.assertTrue(self.path.exists());self.assertFalse(self.panel.active)
 def test_marker_blocks_second_pilot(self):
  AttestedRecoveryLatch(self.path).arm('unrecovered')
  with self.assertRaises(PilotHold):self.runpilot()
  self.assertFalse(self.plant.writes)
 def test_no_live_cli(self):self.assertEqual(main(),2)
 def test_false_claims(self):
  r=self.runpilot();self.assertFalse(r['grid_side_battery_delivery_verified']);self.assertFalse(r['host_loss_recovery_verified'])
 def test_no_unattended_synthetic_expiry(self):
  with self.assertRaises(PilotHold):self.runpilot(presence=lambda:None)
 def test_stale_sample(self):
  with self.assertRaises(PilotHold):self.runpilot(sample=lambda:{'valid':True,'observed_utc':self.clock.utcnow()-dt.timedelta(seconds=20),'soc_pct':50.,'battery_kw':0.,'grid_kw':0.})
 def test_qualification_lost(self):
  with self.assertRaises(PilotHold):self.runpilot(qualify=lambda p,t:self.clock.n<8)
  self.assertEqual(self.plant.register[40029],0)
 def test_audit_before_start(self):
  self.runpilot();names=[e for e,_ in self.events];self.assertLess(names.index('PILOT_LATCH_ARMED'),names.index('PILOT_START_ATTEMPT'))
