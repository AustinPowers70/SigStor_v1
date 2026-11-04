"""RC29b targeted tests for the independent-review findings.
Finding 1: complete, correctly ordered, session-consistent lifecycle with exit/handback cross-checks.
Finding 2: exclusive controller lock held across final readbacks, closure record and latch removal.
"""
import sys,os,json,time,fcntl,pathlib,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
from test_rc29 import Env,S,ev,sample,incident_trace,good_pf,panel_ok,c,RecoveryLatch

def _idx(rows,name):return next(i for i,r in enumerate(rows) if r.get('event')==name)
def _enc(rows):return ''.join(json.dumps(r)+'\n' for r in rows).encode()

class TestSequence(unittest.TestCase):
    def _bad(self,rows,*problems):
        ok,f=c.review_evidence(S,_enc(rows))
        self.assertFalse(ok)
        for p in problems:self.assertIn(p,f['problems'])
    def test_incident_sequence_accepted(self):
        ok,f=c.review_evidence(S,_enc(incident_trace()));self.assertTrue(ok,f['problems'])
    def test_each_required_event_missing(self):
        for name in c.REQUIRED_SEQUENCE:
            with self.subTest(name=name):
                rows=incident_trace();del rows[_idx(rows,name)];self._bad(rows,f'EVENT_{name}_COUNT_0')
    def test_each_required_event_duplicated(self):
        for name in c.REQUIRED_SEQUENCE:
            with self.subTest(name=name):
                rows=incident_trace();i=_idx(rows,name);rows.insert(i,dict(rows[i]));self._bad(rows,f'EVENT_{name}_COUNT_2')
    def test_out_of_order_swap(self):
        rows=incident_trace();i,j=_idx(rows,'DELEGATE_EXIT'),_idx(rows,'DELEGATE_STARTED')
        rows[i],rows[j]=rows[j],rows[i];self._bad(rows,'EVENT_SEQUENCE_OUT_OF_ORDER')
    def test_post_handback_after_result(self):
        rows=incident_trace();rows.append(rows.pop(_idx(rows,'POST_HAND_BACK')));self._bad(rows,'EVENT_SEQUENCE_OUT_OF_ORDER')
    def test_armed_not_first(self):
        rows=incident_trace();rows.insert(_idx(rows,'DELEGATE_STARTED')+1,rows.pop(0));self._bad(rows,'EVENT_SEQUENCE_OUT_OF_ORDER')
    def test_event_session_mismatch(self):
        for name in c.REQUIRED_SEQUENCE:
            with self.subTest(name=name):
                rows=incident_trace();i=_idx(rows,name);rows[i]={**rows[i],'session_id':'deadbeef00'}
                self._bad(rows,f'EVENT_{name}_SESSION_MISMATCH','FOREIGN_OR_UNATTRIBUTED_EVENT')
    def test_unattributed_or_unexpected_event(self):
        rows=incident_trace();rows.insert(2,ev('OPERATOR_NOTE'))
        self._bad(rows,'FOREIGN_OR_UNATTRIBUTED_EVENT','UNEXPECTED_EVENT_IN_TRACE')
    def test_critical_event_with_session_still_rejected(self):
        rows=incident_trace();rows.insert(_idx(rows,'DELEGATE_EXIT'),ev('CRITICAL_DELEGATE_TIMEOUT',session_id=S))
        self._bad(rows,'CRITICAL_EVENT_IN_TRACE','UNEXPECTED_EVENT_IN_TRACE')
    def test_delegate_exit_nonzero_contradicts_result(self):
        rows=incident_trace();i=_idx(rows,'DELEGATE_EXIT');rows[i]={**rows[i],'returncode':2}
        self._bad(rows,'DELEGATE_EXIT_NONZERO','EXIT_CODE_INCONSISTENT')
    def test_delegate_exit_none_timeout_shape(self):
        rows=incident_trace();i=_idx(rows,'DELEGATE_EXIT');rows[i]={**rows[i],'returncode':None}
        self._bad(rows,'DELEGATE_EXIT_NONZERO','EXIT_CODE_INCONSISTENT')
    def test_result_exit_nonzero_contradicts_event(self):
        self._bad(incident_trace(live_controller_exit=1),'CONTROLLER_EXIT_NONZERO','EXIT_CODE_INCONSISTENT')
    def test_post_handback_plant_false_contradicts_result(self):
        rows=incident_trace();i=_idx(rows,'POST_HAND_BACK');rows[i]={**rows[i],'plant_ok':False}
        self._bad(rows,'POST_HANDBACK_PLANT_NOT_OK','HANDBACK_RESULT_INCONSISTENT')
    def test_post_handback_panel_false_contradicts_result(self):
        rows=incident_trace();i=_idx(rows,'POST_HAND_BACK');rows[i]={**rows[i],'panel_ok':False}
        self._bad(rows,'POST_HANDBACK_PANEL_NOT_OK','HANDBACK_RESULT_INCONSISTENT')
    def test_result_handback_false_contradicts_event(self):
        self._bad(incident_trace(plant_handback_verified=False),'SESSION_HANDBACK_NOT_VERIFIED','HANDBACK_RESULT_INCONSISTENT')
    def test_action_mismatch(self):
        self._bad(incident_trace(action='EXPORT'),'ACTION_MISMATCH')

class TestLock(Env):
    def _probe_blocked(self):
        """True if another process cannot take the controller lock right now."""
        pid=os.fork()
        if pid==0:
            try:
                fd=os.open(self.lock,os.O_RDWR)
                try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);os._exit(1)
                except BlockingIOError:os._exit(0)
            except BaseException:os._exit(2)
        _,st=os.waitpid(pid,0);return os.WEXITSTATUS(st)==0
    def _close(self,**kw):
        args=dict(operator_ack=True,input_fn=lambda _:c.challenge_text(S),is_tty=True,latch_path=self.latch,data=self.d,
                  closures=self.clos,preflight=good_pf,panel=panel_ok,lock_path=self.lock,sleep=lambda s:None,now=self.now,operator='t')
        args.update(kw);return c.close(**args)
    def test_lock_held_during_readbacks_record_and_latch_removal(self):
        self.rv();seen={'reads':[],'clear':None,'record':None};test=self
        def pf():seen['reads'].append(test._probe_blocked());return good_pf()
        class SpyLatch(RecoveryLatch):
            def clear_after_independent_recovery(s,*a,**k):
                seen['record']=bool(list(test.clos.glob('*-closure-*')))
                seen['clear']=test._probe_blocked();return super().clear_after_independent_recovery(*a,**k)
        out=self._close(preflight=pf,latch_factory=SpyLatch)
        self.assertEqual(seen['reads'],[True]*c.READBACKS)
        self.assertTrue(seen['record'],'closure record must exist before latch removal')
        self.assertTrue(seen['clear'],'lock must be held at latch removal')
        self.assertFalse(self.latch.exists());self.assertTrue(out['controller_lock_held'])
        self.assertTrue(out['closure_plant_readback']['controller_lock_held_by_closure'])
        self.assertFalse(self._probe_blocked(),'lock must be released afterwards')
    def test_lock_held_while_operator_challenge_pending(self):
        self.rv();seen=[]
        def ask(_):seen.append(self._probe_blocked());return 'wrong'
        with self.assertRaisesRegex(c.ClosureHold,'challenge'):self._close(input_fn=ask)
        self.assertEqual(seen,[True]);self.assertTrue(self.latch.exists())
    def test_busy_controller_lock_blocks_before_any_readback(self):
        self.rv();self.lock.touch();r,w=os.pipe();pid=os.fork()
        if pid==0:
            fd=os.open(self.lock,os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX);os.write(w,b'1');time.sleep(10);os._exit(0)
        os.read(r,1);calls=[]
        try:
            with self.assertRaisesRegex(c.ClosureHold,'controller lock busy'):
                self._close(preflight=lambda:calls.append(1) or good_pf())
        finally:os.kill(pid,9);os.waitpid(pid,0)
        self.assertEqual(calls,[]);self.assertTrue(self.latch.exists())
        self.assertFalse(list(self.clos.glob('*-closure-*')))
    def test_lock_released_after_failed_closure(self):
        self.rv()
        with self.assertRaises(c.ClosureHold):self._close(preflight=lambda:{**good_pf(),'pcs_zero':False,'plant_handback_verified':False})
        self.assertFalse(self._probe_blocked());self.assertTrue(self.latch.exists())
    def test_symlink_lock_rejected(self):
        self.rv();real=self.d/'real.lock';real.touch();self.lock.symlink_to(real)
        with self.assertRaisesRegex(c.ClosureHold,'symlink'):self._close()
        self.assertTrue(self.latch.exists())

if __name__=='__main__':unittest.main()

class TestRealRC27TraceCompatibility(unittest.TestCase):
    """End-to-end: trace produced by the real RC27 orchestrate()/Observation/append (simulated plant)
    must satisfy the RC29b lifecycle checks, and the incident shape must be DEGRADED_ACCEPTABLE."""
    def test_real_writer_trace_passes_review(self):
        import tempfile,types,threading
        import attended_commissioning_rc27 as rc27
        from power_acquisition_rc9 import append
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d);trace=d/'t.jsonl';n=[0];gate=threading.Event()
            def read():
                n[0]+=1;gate.wait(0.02)
                if obs['o'].phase=='AFTER':obs['after']=obs.get('after',0)+1
                if obs.get('after')==2 and not obs.get('bad'):
                    obs['bad']=True;raise ValueError('invalid power sample: home_kw:implausible')
                return {'soc_pct':66.2,'battery_kw':0.4,'grid_kw':1.9,'pv_kw':0.0,'home_kw':1.5}
            obs={}
            def factory(p):
                o=rc27.Observation(p,read=read,writer=append);o.stop.wait=lambda t:time.sleep(0.01);obs['o']=o;return o
            class Child:
                returncode=0
                def communicate(s,timeout):time.sleep(0.4);return ('ok',None)
            class L:
                def arm(s,x):pass
                def clear_after_verified_completion(s,*a):raise AssertionError('must not auto-clear')
            res=rc27.orchestrate('GRID_CHARGE',True,check=lambda a:{'source_slot':'MANUAL_COMMISSIONING_30S','reserve_percent':20},
                consent=lambda a:True,popen=lambda *a,**k:Child(),observer_factory=factory,
                preflight=lambda:{'plant_handback_verified':True},latch_factory=lambda p:L(),
                sleep=lambda s:time.sleep(0.3),panel_check=panel_ok,trace_path=trace)
            self.assertEqual(res['status'],'HOLD_EVIDENCE_REVIEW_HANDBACK_VERIFIED')
            raw=trace.read_bytes()
            # the real ValueError is wrapped as 'ValueError: ...' by Observation, not SampleError -> must be REJECTED
            ok,f=c.review_evidence(res['session_id'],raw)
            lifecycle=[p for p in f['problems'] if p.startswith(('EVENT_','FOREIGN','UNEXPECTED','EXIT_','HANDBACK_','ACTION','DELEGATE','POST_'))]
            self.assertEqual(lifecycle,[],'real RC27 lifecycle must satisfy sequence checks')
            self.assertIn('NON_ALLOWLISTED_INVALID_REASON',f['problems'])
            # same trace with the production SampleError wording is accepted
            fixed=raw.replace(b'ValueError: invalid power sample',b'SampleError: invalid power sample')
            ok,f=c.review_evidence(res['session_id'],fixed)
            self.assertTrue(ok,f['problems']);self.assertEqual(f['evidence_quality'],'DEGRADED_ACCEPTABLE')
