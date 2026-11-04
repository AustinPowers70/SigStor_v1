import unittest,sys,datetime as dt,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'controller'))
import actuator_bridge_rc15 as bridge
import test_rc12

class FakePlant:
    simulation_only=True
    def __init__(self,fail=None):
        self.reg={40029:0,40031:2,40001:0,40032:500}
        self.writes=[];self.fail=fail
    def read_holding(self,a):return self.reg[a]
    def write(self,a,v):
        self.writes.append((a,v))
        if self.fail==a:raise TimeoutError('ambiguous write')
        self.reg[a]=v
    def write_u32(self,a,v):self.write(a,v)
    def call(self,fc,data):
        if fc!=3:raise AssertionError('unexpected FC')
        return bytes([4])+self.reg[40001].to_bytes(4,'big')

class RC15Tests(unittest.TestCase):
    def build(self,action='GRID_CHARGE',fail=None):
        fixture=test_rc12.Tests();k,t,p,l,a,e=fixture.make(action)
        k['plan']['rated_kw']=.5 if action=='GRID_CHARGE' else .65
        plant=FakePlant(fail)
        k['actuator']=bridge.SimulatedActuatorBridge(plant)
        return k,t,p,l,plant,e
    def test_charge_full_transaction(self):
        k,t,p,l,plant,e=self.build()
        r=bridge.execute_rehearsal(**k)
        self.assertEqual(r['modbus_writes'],0);self.assertEqual(plant.reg[40029],0)
        self.assertEqual(plant.reg[40031],2);self.assertTrue(p.active)
        self.assertIn((40032,500),plant.writes)
        self.assertNotIn(40034,[a for a,v in plant.writes])
    def test_export_full_transaction(self):
        k,t,p,l,plant,e=self.build('EXPORT')
        r=bridge.execute_rehearsal(**k)
        self.assertEqual(r['status'],'SIMULATED_COMPLETE')
        self.assertIn((40001,650),plant.writes);self.assertIn((40001,0),plant.writes)
        self.assertEqual(plant.reg[40001],0)
    def test_uncertain_write_handback(self):
        k,t,p,l,plant,e=self.build('GRID_CHARGE',40032)
        with self.assertRaisesRegex(Exception,'ambiguous write'):bridge.execute_rehearsal(**k)
        self.assertIn((40001,0),plant.writes);self.assertTrue(p.active)
    def test_failed_handback_withholds_panel(self):
        k,t,p,l,plant,e=self.build()
        original=plant.write
        def fail_zero(a,v):
            if a==40001 and v==0:raise TimeoutError('handoff failure')
            return original(a,v)
        plant.write=fail_zero
        with self.assertRaisesRegex(Exception,'handback unverified'):bridge.execute_rehearsal(**k)
        self.assertFalse(p.active);self.assertTrue(l.released)
    def test_reject_non_simulated_plant(self):
        pl=FakePlant();pl.simulation_only=False
        with self.assertRaisesRegex(bridge.BridgeError,'simulation-only'):bridge.SimulatedActuatorBridge(pl)
    def test_reject_wrong_power(self):
        for action,power in [('GRID_CHARGE',.65),('EXPORT',.5),('EXPORT',.6501),('GRID_CHARGE',True)]:
            a=bridge.SimulatedActuatorBridge(FakePlant())
            with self.assertRaises(bridge.BridgeError):a.start(action,power)
    def test_changed_qualification_still_handback(self):
        k,t,p,l,plant,e=self.build()
        n=[0]
        def qualify(now):
            n[0]+=1
            return {**k['plan'],**({'source_fingerprint':'changed'} if n[0]>1 else {})}
        k['qualify']=qualify
        with self.assertRaisesRegex(Exception,'qualification'):bridge.execute_rehearsal(**k)
        self.assertEqual(plant.reg[40029],0)
    def test_no_real_interface(self):
        src=(ROOT/'controller'/'actuator_bridge_rc15.py').read_text()
        for forbidden in ['import socket','import pymodbus','subprocess','create_connection']:
            self.assertNotIn(forbidden,src)
    def test_cli_block(self):
        p=subprocess.run([sys.executable,str(ROOT/'controller'/'actuator_bridge_rc15.py')],capture_output=True,text=True)
        self.assertEqual(p.returncode,2);self.assertIn('MODBUS_WRITES=0',p.stdout)
    def test_invalid_actuator_type(self):
        k,*_=self.build();k['actuator']=object()
        with self.assertRaises(bridge.BridgeError):bridge.execute_rehearsal(**k)
if __name__=='__main__':unittest.main()
