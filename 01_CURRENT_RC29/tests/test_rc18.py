import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
from commissioning_preflight_rc18 import inspect

class Fake:
    def __init__(self,remote=0,mode=2,zero=True):self.remote=remote;self.mode=mode;self.zero=zero;self.closed=False
    def read_holding(self,address):return {40029:self.remote,40031:self.mode}[address]
    def call(self,fc,payload):
        assert fc==3 and payload==bytes.fromhex('9c410002')
        return bytes.fromhex('0400000000') if self.zero else bytes.fromhex('0400000001')
    def close(self):self.closed=True

def power():return {'soc_pct':50.0,'battery_kw':-0.4,'grid_kw':-0.1,'pv_kw':0.,'home_kw':0.5}

class Tests(unittest.TestCase):
    def test_verified(self):
        f=Fake();x=inspect(lambda:f,power)
        self.assertTrue(x['plant_handback_verified']);self.assertTrue(f.closed)
    def test_ems_held(self):self.assertFalse(inspect(lambda:Fake(remote=1),power)['plant_handback_verified'])
    def test_wrong_mode(self):self.assertFalse(inspect(lambda:Fake(mode=3),power)['plant_handback_verified'])
    def test_nonzero_pcs(self):self.assertFalse(inspect(lambda:Fake(zero=False),power)['plant_handback_verified'])
    def test_zero_writes(self):self.assertEqual(inspect(lambda:Fake(),power)['modbus_writes'],0)
    def test_no_attribution(self):self.assertFalse(inspect(lambda:Fake(),power)['grid_side_battery_delivery_verified'])
    def test_closed_on_failure(self):
        f=Fake();f.call=lambda *args:(_ for _ in ()).throw(OSError('simulated failure'))
        with self.assertRaises(OSError):inspect(lambda:f,power)
        self.assertTrue(f.closed)
    def test_source_has_no_write_calls(self):
        src=(Path(__file__).resolve().parents[1]/'controller'/'commissioning_preflight_rc18.py').read_text()
        self.assertNotIn('con.write(',src);self.assertNotIn('con.write_u32(',src)
if __name__=='__main__':unittest.main()
