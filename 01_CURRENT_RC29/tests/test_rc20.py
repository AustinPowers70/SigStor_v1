import unittest, datetime as dt, sys, pathlib, struct
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'controller'))
import supervised_session_rc20 as s

UTC=dt.timezone.utc
class Clock:
    def __init__(self):self.sec=0;self.start=dt.datetime(2026,11,4,18,0,tzinfo=UTC)
    def now(self):return self.start+dt.timedelta(seconds=self.sec)
    def tick(self):return self.sec
    def sleep(self,n):self.sec+=n
class Plant:
    def __init__(self):self.values={40029:0,40031:2,40001:0,40032:0};self.writes=[];self.fail_handback=False;self.closed=False
    def read_holding(self,a):return self.values[a]
    def call(self,fc,payload):
        assert fc==3 and payload==struct.pack('>HH',40001,2)
        return b'\x04'+self.values[40001].to_bytes(4,'big')
    def write(self,a,v):self.writes.append((a,v));self.values[a]=v
    def write_u32(self,a,v):
        self.writes.append((a,v))
        if self.fail_handback and a==40001 and v==0:raise RuntimeError('write failed')
        self.values[a]=v
    def close(self):self.closed=True
class Lock:
    def __init__(self,available=True):self.available=available;self.released=False
    def acquire_nonblocking(self):return self.available
    def release(self):self.released=True
class Panel:
    def __init__(self):self.active=True;self.stopped=False;self.started=False
    def is_active(self):return self.active
    def stop(self):self.active=False;self.stopped=True
    def start(self):self.active=True;self.started=True
class Tests(unittest.TestCase):
    def configure(self,action='GRID_CHARGE',recovery=lambda:True,sample=None,qualify=None):
        clock=Clock();plant=Plant();lock=Lock();panel=Panel();events=[]
        auth=s.SessionAuthorization('operator-session-1',action,clock.start+dt.timedelta(seconds=10),True,True,True,True,20,'a'*64)
        kwargs=dict(authorization=auth,plant=plant,lock=lock,panel=panel,
                    qualify=qualify or (lambda now:{'valid':True,'action':action,'slot_end_utc':auth.slot_end_utc,'source_fingerprint':auth.source_fingerprint}),
                    sample=sample or (lambda:{'valid':True,'soc_pct':50.,'battery_kw':-0.5,'grid_kw':0.1,'observed_utc':clock.now()}),
                    audit=lambda evt,detail:events.append((evt,detail)),recovery=recovery,
                    utcnow=clock.now,monotonic=clock.tick,sleep=clock.sleep,duration_limit=5,sample_interval=2)
        return kwargs,plant,lock,panel,events
    def test_successful_charge(self):
        kw,plant,lock,panel,events=self.configure(); result=s.run_injected(**kw)
        self.assertTrue(result['handback_verified']);self.assertTrue(panel.started);self.assertTrue(lock.released)
        self.assertEqual(plant.values[40029],0);self.assertEqual(plant.values[40031],2)
        self.assertFalse(result['grid_side_battery_delivery_verified'])
    def test_successful_export(self):
        kw,plant,_,_,_=self.configure('EXPORT');s.run_injected(**kw)
        self.assertIn((40001,650),plant.writes);self.assertIn((40001,0),plant.writes)
        self.assertNotIn(40034,[a for a,v in plant.writes])
    def test_no_recovery_no_write(self):
        kw,plant,_,panel,_=self.configure(recovery=lambda:False)
        with self.assertRaises(s.SessionHold):s.run_injected(**kw)
        self.assertFalse(plant.writes);self.assertFalse(panel.stopped)
    def test_expired_no_write(self):
        kw,plant,_,panel,_=self.configure();kw['authorization']=s.SessionAuthorization('x','EXPORT',kw['utcnow'](),True,True,True,True,20,'a'*64)
        with self.assertRaises(s.SessionHold):s.run_injected(**kw)
        self.assertFalse(plant.writes);self.assertFalse(panel.stopped)
    def test_loss_qualification_handback(self):
        calls=[0]
        def qualify(now):
            calls[0]+=1
            return {'valid':calls[0]<3,'action':'GRID_CHARGE','slot_end_utc':dt.datetime(2026,11,4,18,0,10,tzinfo=UTC),'source_fingerprint':'a'*64}
        kw,plant,_,panel,_=self.configure(qualify=qualify)
        with self.assertRaises(s.SessionHold):s.run_injected(**kw)
        self.assertEqual(plant.values[40029],0);self.assertTrue(panel.started)
    def test_bad_sample_handback(self):
        kw,plant,_,panel,_=self.configure(sample=lambda:{'valid':False})
        with self.assertRaises(s.SessionHold):s.run_injected(**kw)
        self.assertEqual(plant.values[40029],0);self.assertTrue(panel.started)
    def test_unverified_handback_withholds_panel(self):
        kw,plant,_,panel,events=self.configure();plant.fail_handback=True
        with self.assertRaises(s.CriticalHandback):s.run_injected(**kw)
        self.assertFalse(panel.started);self.assertTrue(any(e[0]=='CRITICAL_HANDBACK_UNVERIFIED' for e in events))
    def test_lock_contention_no_write(self):
        kw,plant,lock,panel,_=self.configure();lock.available=False
        with self.assertRaises(s.SessionHold):s.run_injected(**kw)
        self.assertFalse(plant.writes);self.assertFalse(panel.stopped)
    def test_charge_ceiling_handback(self):
        kw,plant,_,panel,_=self.configure(sample=lambda:{'valid':True,'soc_pct':95.,'battery_kw':0.,'grid_kw':0.,'observed_utc':kw['utcnow']()})
        with self.assertRaises(s.SessionHold):s.run_injected(**kw)
        self.assertEqual(plant.values[40029],0);self.assertTrue(panel.started)
    def test_recovery_loss_mid_session(self):
        count=[0]
        def recovery():count[0]+=1;return count[0]<4
        kw,plant,_,panel,_=self.configure(recovery=recovery)
        with self.assertRaises(s.SessionHold):s.run_injected(**kw)
        self.assertEqual(plant.values[40029],0);self.assertTrue(panel.started)
    def test_cli_blocked(self):self.assertEqual(s.main(),2)
    def test_no_40034_write_source(self):
        import inspect
        source=inspect.getsource(s)
        self.assertNotIn('write(40034',source);self.assertNotIn('write_u32(40034',source)
if __name__=='__main__':unittest.main()
