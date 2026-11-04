import unittest,sys,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
import actuator_contract_rc14 as m
class Plant:
    def __init__(self,fail=None):self.reg={40029:0,40031:2,40001:0};self.calls=[];self.fail=fail
    def read_holding(self,a):self.calls.append(('read',a));return self.reg[a]
    def write(self,a,v):
        self.calls.append(('write',a,v))
        if self.fail==('write',a):raise TimeoutError('ambiguous')
        self.reg[a]=v
    def write_u32(self,a,v):
        self.calls.append(('write_u32',a,v))
        if self.fail==('write_u32',a):raise TimeoutError('ambiguous')
        self.reg[a]=v
    def call(self,fc,data):
        self.calls.append(('call',fc,data));return bytes([4])+self.reg[40001].to_bytes(4,'big')
class Tests(unittest.TestCase):
    def test_charge_sequence(self):
        p=Plant();s=m.PlantSequence(p);s.start('GRID_CHARGE',500)
        self.assertEqual(p.reg[40029],1);self.assertEqual(p.reg[40031],3)
        self.assertEqual([x for x in p.calls if x[0].startswith('write')], [('write_u32',40032,500),('write',40031,3),('write',40029,1)])
        self.assertTrue(s.handback());self.assertEqual(p.reg[40001],0)
    def test_export_sequence(self):
        p=Plant();s=m.PlantSequence(p);s.start('EXPORT',650)
        self.assertEqual(p.reg[40001],650);self.assertTrue(s.handback())
    def test_cannot_repeat_start(self):
        s=m.PlantSequence(Plant());s.start('GRID_CHARGE',500)
        with self.assertRaises(m.ActuatorContractError):s.start('GRID_CHARGE',500)
    def test_reject_oversize(self):
        for action,w in [('GRID_CHARGE',501),('EXPORT',651),('EXPORT',500),('BAD',650)]:
            p=Plant();s=m.PlantSequence(p)
            with self.assertRaises(m.ActuatorContractError):s.start(action,w)
            self.assertFalse(s.attempted)
    def test_reject_existing_ems(self):
        p=Plant();p.reg[40029]=1;s=m.PlantSequence(p)
        with self.assertRaises(m.ActuatorContractError):s.start('EXPORT',650)
        self.assertFalse(any(c[0].startswith('write') for c in p.calls))
    def test_ambiguous_first_write_needs_handback(self):
        p=Plant(('write_u32',40032));s=m.PlantSequence(p)
        with self.assertRaises(TimeoutError):s.start('GRID_CHARGE',500)
        self.assertTrue(s.attempted)
        self.assertTrue(s.handback())
    def test_zero_pcs_required(self):
        p=Plant();s=m.PlantSequence(p);s.start('EXPORT',650);p.fail=('write_u32',40001)
        self.assertFalse(s.handback())
    def test_partial_handback_continues(self):
        p=Plant();s=m.PlantSequence(p);s.start('GRID_CHARGE',500);p.fail=('write',40031)
        self.assertFalse(s.handback());self.assertIn(('write',40029,0),p.calls)
    def test_policy_is_not_live_authorization(self):
        keys=['operator_approval','manual_authority','exclusive_lock','authority_isolated','rc13_research_only','source_fresh','slot_active','reserve_ok','telemetry_ready']
        d={k:True for k in keys};v=m.operator_policy(**d)
        self.assertTrue(v['prerequisites_met']);self.assertFalse(v['production_execution_enabled'])
        for k in keys:
            x=d.copy();x[k]=False;self.assertFalse(m.operator_policy(**x)['prerequisites_met'])
    def test_no_40034_writes(self):
        s=(Path(__file__).resolve().parents[1]/'controller'/'actuator_contract_rc14.py').read_text()
        self.assertNotIn('write(40034',s);self.assertNotIn('write_u32(40034',s)
    def test_no_direct_live_cli(self):
        self.assertEqual(m.main(),2)
    def test_rc14_execute_block(self):
        x=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'controller'/'commissioning_readiness_rc14.py'),'--execute-slot'],capture_output=True,text=True)
        self.assertEqual(x.returncode,2);self.assertIn('MODBUS_WRITES=0',x.stdout)
if __name__=='__main__':unittest.main()
