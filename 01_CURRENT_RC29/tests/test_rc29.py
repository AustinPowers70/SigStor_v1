import sys,json,os,unittest,tempfile,types,datetime as dt,pathlib,hashlib,fcntl
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent.parent/'controller'))
import latch_closure_rc29 as c
import attended_commissioning_rc27 as rc27
from recovery_latch_rc21 import RecoveryLatch

S='8d39f77fc0e244b69f79f0257b56ba07'
T=c.TRACE_SCHEMA

def sample(phase,valid=True,error=None):
    r={'schema':T,'record_type':'PLANT_SAMPLE','phase':phase,'valid':valid,'modbus_writes_by_observer':0,'timestamp_utc':'2026-11-04T18:49:00+00:00'}
    if error:r['error']=error
    return r
def ev(name,**kw):return {'schema':T,'record_type':'SESSION_EVENT','event':name,**kw}
HOME='SampleError: invalid power sample: home_kw:implausible'
def incident_trace(**override):
    """Reconstruction of the 4 Nov session shape: 3/16/3 valid + 1 AFTER home_kw invalid."""
    res=dict(session_id=S,action='GRID_CHARGE',status='HOLD_RECOVERY_REQUIRED',live_controller_exit=0,delegate_timeout=False,
             observer_error=None,plant_handback_verified=True,panel_restored=True,modbus_writes_by_observer=0)
    res.update(override)
    rows=[ev('SESSION_LATCH_ARMED',session_id=S,action='GRID_CHARGE',slot='MANUAL_COMMISSIONING_30S')]+[sample('BEFORE')]*3+[ev('DELEGATE_STARTED',session_id=S,command='--execute-30s-charge')]
    rows+=[sample('DURING')]*16+[ev('DELEGATE_EXIT',session_id=S,returncode=0)]
    rows+=[sample('AFTER')]*2+[sample('AFTER',False,HOME)]+[sample('AFTER')]
    rows+=[ev('POST_HAND_BACK',session_id=S,plant_ok=True,panel_ok=True),ev('SESSION_RESULT',**res)]
    return rows

def good_pf():
    return {'remote_ems_off':True,'self_consumption':True,'pcs_zero':True,'soc_pct':66.2,
            'plant_handback_verified':True,'modbus_writes':0,'timestamp_utc':'x'}
def panel_ok(*a):return types.SimpleNamespace(returncode=0,stdout='active\n')
def panel_bad(*a):return types.SimpleNamespace(returncode=3,stdout='inactive\n')

class Env(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=pathlib.Path(self.tmp.name)
        self.latch=self.d/'rc28-recovery-required.json';self.clos=self.d/'closures';self.lock=self.d/'x.lock'
        RecoveryLatch(self.latch).arm(S)
        self.write_trace(incident_trace())
        self.clock=dt.datetime(2026,11,5,9,0,tzinfo=dt.timezone.utc)
    def tearDown(self):self.tmp.cleanup()
    def write_trace(self,rows):
        p=self.d/f'rc27-pilot-{S}.jsonl'
        if p.exists():p.chmod(0o600);p.unlink()
        p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    def now(self):return self.clock
    def rv(self,pf=good_pf,panel=panel_ok):
        return c.review(latch_path=self.latch,data=self.d,closures=self.clos,preflight=pf,panel=panel,lock_path=self.lock,sleep=lambda s:None,now=self.now)
    def cl(self,answer=None,ack=True,tty=True,pf=good_pf,panel=panel_ok):
        answer=answer if answer is not None else c.challenge_text(S)
        return c.close(operator_ack=ack,input_fn=lambda _:answer,is_tty=tty,latch_path=self.latch,data=self.d,
                       closures=self.clos,preflight=pf,panel=panel,lock_path=self.lock,sleep=lambda s:None,now=self.now,operator='test')

class TestEvidence(Env):
    def test_incident_shape_is_degraded_acceptable(self):
        r=self.rv()
        self.assertTrue(r['evidence_acceptable']);self.assertTrue(r['plant_recovery_verified'])
        self.assertEqual(r['evidence']['evidence_quality'],'DEGRADED_ACCEPTABLE')
        self.assertEqual(r['evidence']['valid_counts'],{'BEFORE':3,'DURING':16,'AFTER':3})
        self.assertTrue(r['eligible_for_operator_closure']);self.assertEqual(r['modbus_writes'],0)
        self.assertTrue(self.latch.exists(),'review must never clear the latch')
    def _bad(self,rows,problem):
        ok,f=c.review_evidence(S,''.join(json.dumps(r)+'\n' for r in rows).encode())
        self.assertFalse(ok);self.assertIn(problem,f['problems'])
    def test_nonzero_exit_rejected(self):self._bad(incident_trace(live_controller_exit=2),'CONTROLLER_EXIT_NONZERO')
    def test_timeout_rejected(self):self._bad(incident_trace(delegate_timeout=True),'DELEGATE_TIMEOUT')
    def test_handback_unverified_rejected(self):self._bad(incident_trace(plant_handback_verified=False),'SESSION_HANDBACK_NOT_VERIFIED')
    def test_panel_rejected(self):self._bad(incident_trace(panel_restored=False),'PANEL_NOT_RESTORED')
    def test_comm_error_not_allowlisted(self):
        rows=incident_trace();rows.insert(5,sample('AFTER',False,'TimeoutError: timed out'))
        self._bad(rows,'NON_ALLOWLISTED_INVALID_REASON')
    def test_mixed_flags_not_allowlisted(self):
        rows=incident_trace();rows.insert(5,sample('AFTER',False,'SampleError: invalid power sample: home_kw:implausible,battery_kw:out_of_range'))
        self._bad(rows,'NON_ALLOWLISTED_INVALID_REASON')
    def test_invalid_during_actuation_rejected(self):
        rows=incident_trace();rows.insert(6,sample('DURING',False,HOME))
        self._bad(rows,'INVALID_SAMPLE_DURING_ACTUATION')
    def test_too_many_invalid(self):
        rows=incident_trace()+[sample('AFTER',False,HOME)]*2
        self._bad(rows,'TOO_MANY_INVALID_SAMPLES')
    def test_coverage(self):
        rows=[r for r in incident_trace() if not (r.get('phase')=='AFTER' and r.get('valid'))]
        self._bad(rows,'INSUFFICIENT_VALID_AFTER')
    def test_critical_event(self):
        rows=incident_trace();rows.insert(1,ev('CRITICAL_DELEGATE_TIMEOUT',session_id=S))
        self._bad(rows,'CRITICAL_EVENT_IN_TRACE')
    def test_session_mismatch(self):
        rows=incident_trace();rows[0]=ev('SESSION_LATCH_ARMED',session_id='other1234',action='GRID_CHARGE')
        self._bad(rows,'EVENT_SESSION_LATCH_ARMED_SESSION_MISMATCH')
    def test_missing_result(self):
        self._bad(incident_trace()[:-1],'EVENT_SESSION_RESULT_COUNT_0')

class TestPlantRecovery(Env):
    def test_any_readback_not_handed_back_blocks(self):
        calls=[]
        def pf():
            calls.append(1);r=good_pf()
            if len(calls)==2:r.update(remote_ems_off=False,plant_handback_verified=False)
            return r
        r=self.rv(pf=pf);self.assertFalse(r['plant_recovery_verified']);self.assertFalse(r['eligible_for_operator_closure'])
        self.assertEqual(len(calls),c.READBACKS)
    def test_panel_inactive_blocks(self):
        self.assertFalse(self.rv(panel=panel_bad)['eligible_for_operator_closure'])
    def test_lock_held_blocks(self):
        self.lock.touch()
        with open(self.lock,'rb') as fp:
            fcntl.flock(fp,fcntl.LOCK_EX)
            pid=os.fork()
            if pid==0:
                ok,p=c.fresh_plant_recovery(good_pf,panel_ok,self.lock,sleep=lambda s:None);os._exit(0 if not p['controller_lock_free'] else 1)
            _,st=os.waitpid(pid,0)
        self.assertEqual(os.WEXITSTATUS(st),0)
    def test_preflight_exception_propagates(self):
        def pf():raise ConnectionError('no route')
        with self.assertRaises(ConnectionError):self.rv(pf=pf)
        self.assertTrue(self.latch.exists())

class TestClosure(Env):
    def test_full_operator_witnessed_closure(self):
        self.rv();self.clock+=dt.timedelta(seconds=60)
        out=self.cl()
        self.assertEqual(out['status'],'LATCH_CLEARED_OPERATOR_WITNESSED')
        self.assertFalse(self.latch.exists())
        names=sorted(p.name.split('-')[1] for p in self.clos.iterdir())
        self.assertEqual(names,['cleared','closure','review'])
        rec=json.loads(next(self.clos.glob('*-closure-*')).read_text())
        self.assertFalse(rec['further_pilots_authorised']);self.assertFalse(rec['physical_delivery_verified'])
        self.assertEqual(rec['modbus_writes'],0)
    def test_no_review_blocks(self):
        with self.assertRaisesRegex(c.ClosureHold,'no review'):self.cl()
        self.assertTrue(self.latch.exists())
    def test_ineligible_review_blocks(self):
        self.rv(panel=panel_bad)
        with self.assertRaisesRegex(c.ClosureHold,'not eligible'):self.cl()
        self.assertTrue(self.latch.exists())
    def test_expired_review_blocks(self):
        self.rv();self.clock+=dt.timedelta(seconds=c.REVIEW_TTL_S+1)
        with self.assertRaisesRegex(c.ClosureHold,'expired'):self.cl()
        self.assertTrue(self.latch.exists())
    def test_wrong_challenge_blocks(self):
        self.rv()
        with self.assertRaisesRegex(c.ClosureHold,'challenge'):self.cl(answer='yes')
        self.assertTrue(self.latch.exists())
    def test_no_tty_or_ack_blocks(self):
        self.rv()
        with self.assertRaisesRegex(c.ClosureHold,'TTY'):self.cl(tty=False)
        with self.assertRaisesRegex(c.ClosureHold,'operator-ack'):self.cl(ack=False)
        self.assertTrue(self.latch.exists())
    def test_trace_tamper_blocks(self):
        self.rv();rows=incident_trace();rows.append(sample('AFTER'));self.write_trace(rows)
        with self.assertRaisesRegex(c.ClosureHold,'trace changed'):self.cl()
        self.assertTrue(self.latch.exists())
    def test_latch_replaced_blocks(self):
        self.rv();self.latch.unlink();RecoveryLatch(self.latch).arm(S)  # new armed_utc -> new hash
        with self.assertRaisesRegex(c.ClosureHold,'latch changed'):self.cl()
    def test_plant_regressed_at_closure_blocks(self):
        self.rv()
        bad=lambda:{**good_pf(),'pcs_zero':False,'plant_handback_verified':False}
        with self.assertRaisesRegex(c.ClosureHold,'fresh plant readback failed'):self.cl(pf=bad)
        self.assertTrue(self.latch.exists())
        self.assertFalse(list(self.clos.glob('*-closure-*')),'no closure record when blocked')
    def test_symlink_latch_rejected(self):
        real=self.d/'real.json';self.latch.rename(real);self.latch.symlink_to(real)
        with self.assertRaises(c.ClosureHold):c.read_latch(self.latch)
    def test_no_modbus_import(self):
        src=pathlib.Path(c.__file__).read_text()
        for bad in ('write_u32','.write(4','socket','40034'):self.assertNotIn(bad,src.split('"""',2)[2])

class TestRC27Separation(unittest.TestCase):
    def _run(self,child_exit=0,invalid=0,handback=True):
        class L:
            def __init__(s):s.cleared=False
            def arm(s,x):pass
            def clear_after_verified_completion(s,x,v):s.cleared=True
        class O:
            def __init__(s):
                s.counts={'BEFORE':3,'DURING':16,'AFTER':3};s.invalid=invalid;s.error=None
                s.invalid_by_phase={'BEFORE':0,'DURING':0,'AFTER':invalid};s.invalid_reasons=[{'phase':'AFTER','error':HOME}]*invalid
                s.stop=types.SimpleNamespace(set=lambda:None)
            def run(s):pass
            def event(s,*a,**k):pass
        class C:
            returncode=child_exit
            def communicate(s,timeout):return ('',None)
        st={}
        def lf(p):st['l']=L();return st['l']
        r=rc27.orchestrate('GRID_CHARGE',True,check=lambda a:{'source_slot':'x','reserve_percent':20},consent=lambda a:True,
            popen=lambda *a,**k:C(),observer_factory=lambda p:O(),preflight=lambda:{'plant_handback_verified':handback},
            latch_factory=lf,sleep=lambda s:None,panel_check=panel_ok)
        return r,st['l']
    def test_incident_now_distinct_status_latch_retained(self):
        r,l=self._run(invalid=1)
        self.assertEqual(r['status'],'HOLD_EVIDENCE_REVIEW_HANDBACK_VERIFIED')
        self.assertTrue(r['handback_proven']);self.assertFalse(r['evidence_complete'])
        self.assertFalse(l.cleared,'automatic clear must remain strict');self.assertTrue(r['recovery_latch_retained'])
        self.assertEqual(r['invalid_by_phase']['AFTER'],1)
    def test_clean_still_auto_clears(self):
        r,l=self._run();self.assertEqual(r['status'],'SUPERVISED_PILOT_HANDBACK_CONFIRMED');self.assertTrue(l.cleared)
    def test_handback_failure_still_recovery_required(self):
        r,l=self._run(handback=False);self.assertEqual(r['status'],'HOLD_RECOVERY_REQUIRED');self.assertFalse(l.cleared)
        r,l=self._run(child_exit=2,invalid=1);self.assertEqual(r['status'],'HOLD_RECOVERY_REQUIRED')

if __name__=='__main__':unittest.main()
