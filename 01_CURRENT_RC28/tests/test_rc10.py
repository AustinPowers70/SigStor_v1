import sys,unittest,datetime as dt
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
import qualified_observation_rc10 as x
UTC=dt.timezone.utc
class Clock:
 def __init__(self):self.t=0.;self.start=dt.datetime(2026,11,1,18,0,tzinfo=UTC)
 def mono(self):return self.t
 def utc(self):return self.start+dt.timedelta(seconds=self.t)
 def sleep(self,sec):self.t+=sec
class RC10Tests(unittest.TestCase):
 def setUp(self):
  self.c=Clock();self.log=[]
  self.plan={'state':'QUALIFIED_SIMULATION_ONLY','dispatch_enabled':False,'action':'GRID_CHARGE',
   'start_utc':self.c.utc().isoformat(),'end_utc':(self.c.utc()+dt.timedelta(seconds=1800)).isoformat(),
   'source_fingerprint':'pinned'}
  self.data={'soc_pct':50.,'battery_kw':0.5,'grid_kw':0.6,'pv_kw':0.,'home_kw':0.1}
 def run_it(self,**kwargs):
  opts=dict(plan=self.plan,qualify=lambda now:self.plan,read=lambda:self.data,sample_write=self.log.append,
    clock=self.c.mono,utcnow=self.c.utc,sleep=self.c.sleep,maximum_seconds=6,interval_seconds=2)
  opts.update(kwargs);return x.observe(**opts)
 def test_samples_no_writes(self):
  out=self.run_it();self.assertEqual(out['samples'],3);self.assertEqual(out['modbus_writes'],0)
 def test_source_change_abort(self):
  with self.assertRaisesRegex(x.ObservationError,'qualification changed'):
   self.run_it(qualify=lambda now:{**self.plan,'source_fingerprint':'changed'})
 def test_invalid_power_abort(self):
  with self.assertRaisesRegex(x.ObservationError,'invalid power'):self.run_it(read=lambda:{**self.data,'grid_kw':float('nan')})
 def test_soc_guard(self):
  with self.assertRaisesRegex(x.ObservationError,'ceiling'):self.run_it(read=lambda:{**self.data,'soc_pct':95})
 def test_invalid_plan(self):
  with self.assertRaisesRegex(x.ObservationError,'qualified advisory'):self.run_it(plan={**self.plan,'dispatch_enabled':True})
 def test_slot_expired(self):
  with self.assertRaisesRegex(x.ObservationError,'expired'):self.run_it(plan={**self.plan,'end_utc':(self.c.utc()-dt.timedelta(seconds=1)).isoformat()})
 def test_clock_jump(self):
  def jump():return self.c.utc()+dt.timedelta(seconds=10 if self.c.t else 0)
  with self.assertRaisesRegex(x.ObservationError,'clock discontinuity'):self.run_it(utcnow=jump)
 def test_gap(self):
  def slow(sec):self.c.t+=12
  with self.assertRaisesRegex(x.ObservationError,'sampling gap'):self.run_it(sleep=slow,maximum_seconds=30)
 def test_no_actuator_import(self):
  source=Path(x.__file__).read_text();self.assertNotIn('supervised_charge',source);self.assertNotIn('supervised_export',source)
 def test_cli_write_block(self):self.assertEqual(x.main(['--execute-slot']),2)
 def test_no_action_main(self):
  original=x.preflight
  try:
   x.preflight=lambda now:{'state':'HOLD','reason':'OUTSIDE_HORIZON'}
   self.assertEqual(x.main([]),0)
  finally:x.preflight=original
if __name__=='__main__':unittest.main()
