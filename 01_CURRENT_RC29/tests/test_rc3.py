import sys,unittest,datetime as dt
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
import bounded_session as b
NOW=dt.datetime(2026,11,1,17,0,tzinfo=dt.timezone.utc)
class Clock:
 def __init__(self):self.t=0
 def monotonic(self):return self.t
 def now(self):return NOW+dt.timedelta(seconds=self.t)
 def sleep(self,sec):self.t+=sec
class Plant:
 def __init__(self,handback=True):self.started=0;self.released=0;self.handback_result=handback
 def start(self,action):self.started+=1
 def handback(self):self.released+=1;return self.handback_result
class Tests(unittest.TestCase):
 def slot(self,seconds=8,action='GRID_CHARGE'):
  return {'end_utc':(NOW+dt.timedelta(seconds=seconds)).isoformat(),'action':action}
 def run_(self,seconds=8,plant=None,validate=lambda:None,telemetry=None,clock=None,action='GRID_CHARGE'):
  c=clock or Clock(); p=plant or Plant();events=[]
  if telemetry is None:telemetry=lambda:{'valid':True,'observed_utc':c.now().isoformat(),'soc_pct':50,'battery_kw':0.5,'reserve_pct':20}
  result=b.run_simulated(slot=self.slot(seconds,action),validate=validate,plant=p,telemetry=telemetry,
        record=lambda e,d:events.append(e),utcnow=c.now,monotonic=c.monotonic,sleep=c.sleep)
  return result,p,events
 def test_completes(self):
  result,p,e=self.run_();self.assertEqual(p.released,1);self.assertGreaterEqual(result['samples'],2)
 def test_single_start(self):self.assertEqual(self.run_()[1].started,1)
 def test_zero_writes(self):self.assertEqual(self.run_()[0]['modbus_writes'],0)
 def test_no_grid_side_claim(self):self.assertFalse(self.run_()[0]['grid_side_delivery_verified'])
 def test_fail_handback(self):
  p=Plant(False)
  with self.assertRaisesRegex(b.SessionFailure,'CRITICAL'):self.run_(plant=p)
  self.assertEqual(p.released,1)
 def test_abort_qualify(self):
  p=Plant();n=[0]
  def check():
   n[0]+=1
   if n[0]==3:raise ValueError('stale')
  with self.assertRaisesRegex(b.SessionFailure,'aborted'):self.run_(plant=p,validate=check)
  self.assertEqual(p.released,1)
 def test_abort_telemetry(self):
  p=Plant()
  with self.assertRaisesRegex(b.SessionFailure,'aborted'):self.run_(plant=p,telemetry=lambda:{'valid':False})
  self.assertEqual(p.released,1)
 def test_reserve(self):
  p=Plant();c=Clock()
  def tele():return {'valid':True,'observed_utc':c.now().isoformat(),'soc_pct':21,'battery_kw':-0.65,'reserve_pct':20}
  with self.assertRaisesRegex(b.SessionFailure,'aborted'):self.run_(plant=p,telemetry=tele,clock=c,action='EXPORT')
  self.assertEqual(p.released,1)
 def test_charge_soc(self):
  p=Plant();c=Clock()
  def tele():return {'valid':True,'observed_utc':c.now().isoformat(),'soc_pct':96,'battery_kw':0.5,'reserve_pct':20}
  with self.assertRaisesRegex(b.SessionFailure,'aborted'):self.run_(plant=p,telemetry=tele,clock=c)
  self.assertEqual(p.released,1)
 def test_wall_clock_jump(self):
  p=Plant();c=Clock();c.sleep(0)
  class Jump(Clock):
   def now(self):return NOW+dt.timedelta(seconds=self.t+(100 if self.t>=2 else 0))
  with self.assertRaisesRegex(b.SessionFailure,'aborted'):self.run_(seconds=200,plant=p,clock=Jump())
  self.assertEqual(p.released,1)
 def test_bad_slot(self):
  with self.assertRaisesRegex(b.SessionFailure,'expired'):b.run_simulated(slot=self.slot(0),validate=lambda:None,plant=Plant(),telemetry=lambda:None,record=lambda a,b:None,utcnow=lambda:NOW,monotonic=lambda:0,sleep=lambda x:None)
 def test_duration_cap(self):
  c=Clock();p=Plant();e=[]
  out=b.run_simulated(slot=self.slot(4000),validate=lambda:None,plant=p,
    telemetry=lambda:{'valid':True,'observed_utc':c.now().isoformat(),'soc_pct':50,'battery_kw':0,'reserve_pct':20},
    record=lambda a,b:e.append(a),utcnow=c.now,monotonic=c.monotonic,sleep=c.sleep)
  self.assertEqual(c.t,1800);self.assertEqual(p.released,1)
 def test_action_mismatch(self):
  q={'Decision':'EXPORT','AuthorityManualReady':True,'StartUtc':NOW.isoformat(),'ScheduledEnergyKwh':0.05}
  r={'active_slot':{'action':'GRID_CHARGE','start_utc':NOW.isoformat(),'target_grid_side_kwh':0.05}}
  with self.assertRaisesRegex(b.SessionFailure,'mismatch'):b.check_slot(q,r,NOW)
 def test_incapable_remaining(self):
  q={'Decision':'GRID_CHARGE','AuthorityManualReady':True,'StartUtc':(NOW-dt.timedelta(minutes=29)).isoformat(),'ScheduledEnergyKwh':0.2}
  r={'active_slot':{'action':'GRID_CHARGE','start_utc':q['StartUtc'],'target_grid_side_kwh':0.2}}
  with self.assertRaisesRegex(b.SessionFailure,'cannot be delivered'):b.check_slot(q,r,NOW)
 def test_no_live_actuator_imports(self):
  src=(Path(__file__).resolve().parents[1]/'controller'/'bounded_session.py').read_text()
  self.assertNotIn('from supervised_charge import',src)
  self.assertNotIn('from supervised_export import',src)
 def test_no_40034_write(self):
  src=(Path(__file__).resolve().parents[1]/'controller'/'bounded_session.py').read_text()
  self.assertNotIn('write(40034',src)
  self.assertNotIn('write_u32(40034',src)
if __name__=='__main__':unittest.main()
