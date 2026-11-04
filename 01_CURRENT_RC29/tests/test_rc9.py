import importlib.util,unittest,tempfile,pathlib,json,types,struct,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('rc9',ROOT/'controller'/'power_acquisition_rc9.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Clock:
 def __init__(self):self.t=0
 def now(self):return self.t
 def sleep(self,d):self.t+=d
class PowerTests(unittest.TestCase):
 def test_decode_commissioned_indices(self):
  legacy=m.original_reader();regs=[0]*34
  regs[0],regs[1]=0,700;regs[9]=845;regs[30],regs[31]=0,0
  neg=(2**32-650);regs[32],regs[33]=neg>>16,neg&65535
  self.assertEqual(legacy.signed32(regs,32),-650)
  self.assertEqual(regs[9]/10,84.5)
  self.assertEqual(legacy.signed32(regs,0),700)
 def test_sample_uses_30005_and_fc04(self):
  class R:
   def read_plant(self,*args):
    self.args=args;return dict(grid_kw=.7,battery_kw=-.65,pv_kw=0,soc_pct=80)
   def validate_sample(self,data,max_kw):
    data['valid']=1;data['home_kw']=1.35;return data
  r=R();out=m.sample_once(r)
  self.assertEqual(r.args,(m.HOST,502,247,2.0,30005));self.assertEqual(out['battery_kw'],-.65)
 def test_invalid_sample(self):
  class R:
   def read_plant(self,*args):return dict(grid_kw=0,battery_kw=0,pv_kw=0,soc_pct=101)
   def validate_sample(self,d,max_kw):d['valid']=0;d['issues']='bad';return d
  with self.assertRaises(m.SampleError):m.sample_once(R())
 def test_bounded_and_append_only(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'journal';c=Clock()
   read=lambda:dict(soc_pct=80,battery_kw=-.65,grid_kw=.7,pv_kw=0,home_kw=1.35)
   result=m.run(5,2,p,read=read,clock=c.now,sleep=c.sleep)
   rows=[json.loads(l) for l in p.read_text().splitlines()]
   self.assertEqual(result['samples'],3);self.assertEqual(len(rows),3)
   self.assertTrue(all(x['modbus_writes']==0 for x in rows))
   self.assertTrue(all(x['battery_grid_side_delivery_verified'] is False for x in rows))
 def test_invalid_read_recorded(self):
  with tempfile.TemporaryDirectory() as d:
   c=Clock();p=pathlib.Path(d)/'a'
   result=m.run(2,1,p,read=lambda: (_ for _ in ()).throw(OSError('oops')),clock=c.now,sleep=c.sleep)
   self.assertEqual(result['failed_reads'],2)
   self.assertTrue(all(not json.loads(x)['valid'] for x in p.read_text().splitlines()))
 def test_bad_bounds(self):
  for duration,interval in [(0,2),(1801,2),(3,0),(3,11)]:
   with self.assertRaises(m.SampleError):m.run(duration,interval,'unused')
 def test_symlink(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'a';p.symlink_to(pathlib.Path(d)/'b')
   with self.assertRaises(m.SampleError):m.append(p,{'valid':True})
 def test_no_network_write_api(self):
  src=(ROOT/'controller'/'power_acquisition_rc9.py').read_text()
  self.assertNotIn('write_register',src)
  self.assertNotIn('supervised_charge',src)
  self.assertNotIn('supervised_export',src)
 def test_actuation_block(self):
  self.assertEqual(m.main(['--execute-slot']),2)
 def test_original_decoder_unchanged(self):
  import hashlib
  original=pathlib.Path('/mnt/data/telemetry_src/sigen_telemetry_v4_4_6_5.py')
  if original.exists():
   self.assertEqual(hashlib.sha256(original.read_bytes()).digest(),hashlib.sha256((ROOT/'accepted'/'telemetry'/original.name).read_bytes()).digest())
 def test_nonfinite_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   c=Clock()
   with self.assertRaises(m.SampleError):m.run(2,1,pathlib.Path(d)/'a',read=lambda:dict(soc_pct=float('nan'),battery_kw=0,grid_kw=0,pv_kw=0,home_kw=0),clock=c.now,sleep=c.sleep)
