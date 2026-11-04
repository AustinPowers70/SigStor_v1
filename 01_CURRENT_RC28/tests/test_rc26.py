import unittest,sys,pathlib,tempfile,datetime as dt
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'controller'))
from commissioning_capture_rc26 import capture,assess,CaptureHold,SCHEMA
class Tests(unittest.TestCase):
 def test_capture_integrates_real_signed_port_units(self):
  state={'t':0};origin=dt.datetime(2026,11,4,tzinfo=dt.timezone.utc);rows=[]
  def read():return {'soc_pct':60.,'battery_kw':7.2,'grid_kw':3.6,'pv_kw':0.,'home_kw':0.}
  capture(seconds=30,interval=2,read=read,now=lambda:origin+dt.timedelta(seconds=state['t']),
      clock=lambda:state['t'],sleep=lambda n:state.__setitem__('t',state['t']+n),write=lambda p,r:rows.append(r),path='/unused')
  out=assess(rows)
  self.assertEqual(out['status'],'REVIEW_TRACE');self.assertEqual(out['valid_samples'],15)
  self.assertAlmostEqual(out['battery_port_wh_signed_positive_charging'],56.,places=3)
  self.assertFalse(out['battery_grid_side_delivery_verified'])
 def test_stale_trace_hold(self):
  origin=dt.datetime(2026,11,4,tzinfo=dt.timezone.utc)
  rows=[{'schema':SCHEMA,'utc':(origin+dt.timedelta(seconds=t)).isoformat(),'valid':True,
         'soc_pct':60.,'battery_kw':0.,'grid_kw':0.,'home_kw':0.,'modbus_writes':0} for t in (0,12)]
  self.assertEqual(assess(rows)['status'],'HOLD_INCOMPLETE_TRACE')
 def test_invalid_power_fails(self):
  origin=dt.datetime(2026,11,4,tzinfo=dt.timezone.utc)
  rows=[{'schema':SCHEMA,'utc':(origin+dt.timedelta(seconds=t)).isoformat(),'valid':True,
         'soc_pct':60.,'battery_kw':float('nan'),'grid_kw':0.,'home_kw':0.,'modbus_writes':0} for t in (0,2)]
  with self.assertRaises(CaptureHold):assess(rows)
 def test_capture_no_modbus_writes(self):
  state={'t':0};rows=[];origin=dt.datetime(2026,11,4,tzinfo=dt.timezone.utc)
  r=capture(seconds=30,interval=2,read=lambda:{'soc_pct':60.,'battery_kw':0.,'grid_kw':0.,'pv_kw':0.,'home_kw':0.},
      now=lambda:origin+dt.timedelta(seconds=state['t']),clock=lambda:state['t'],
      sleep=lambda n:state.__setitem__('t',state['t']+n),write=lambda p,r:rows.append(r),path='/unused')
  self.assertEqual(r['modbus_writes'],0)
 def test_wrong_schema(self):
  with self.assertRaises(CaptureHold):assess([{'schema':'fake'},{'schema':'fake'}])
