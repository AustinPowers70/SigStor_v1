#!/usr/bin/env python3
"""RC29 operator-witnessed recovery-latch closure. NO Modbus writes, ever.

Purpose: close a RECOVERY_REQUIRED latch left by an attended pilot whose
controller exited cleanly and whose handback was verified, but whose evidence
was degraded (e.g. one derived `home_kw:implausible` sample).

Two separate questions, answered separately and both recorded:
  A. EVIDENCE REVIEW  - is the hash-verified session trace consistent with a clean,
     handed-back session? Invalid samples are accepted only if every reason is
     on a narrow allowlist of derived-plausibility flags.
  B. PLANT RECOVERY   - is the plant handed back NOW? Proven only by fresh
     read-only FC03/FC04 readback (Remote EMS 0, mode 2, PCS request 0),
     repeated, plus authority panel active and controller lock free.

`--review` is read-only and writes a short-lived review record (expiry
REVIEW_TTL_S). `--close --operator-ack` requires a local TTY, a typed
session-specific challenge, an unexpired review whose latch and trace hashes
still match, and a second fresh plant readback. The exclusive controller lock
is held from before the final readbacks until after latch removal. A write-once
(O_EXCL, mode 0400) closure record is fsynced BEFORE the latch is removed via
RecoveryLatch's proof-gated API. Trace and records are hash-verified, not
immutable: root can still alter them, which the hash check detects only
between review and closure.

This does NOT provide host-loss recovery, does NOT attest battery-attributable
grid-side energy, and does NOT authorise any further pilot.
"""
import argparse, datetime as dt, fcntl, hashlib, json, os, pathlib, stat, sys, time

DATA=pathlib.Path('/opt/sigenstor/data/rtm')
LATCH=DATA/'rc28-recovery-required.json'
CLOSURES=DATA/'rc29-latch-closures'
LOCK=pathlib.Path('/run/lock/sigen-rtm-v12-commission.lock')
AUTH_UNIT='sigen-rtm-authority-panel.service'
TRACE_SCHEMA='SIGEN_PHASE3B_RC27_ATTENDED_PILOT_CORRELATION'
SCHEMA='SIGEN_PHASE3B_RC29_LATCH_CLOSURE'
REVIEW_TTL_S=600
READBACKS=3
READBACK_GAP_S=2.0
MIN_VALID={'BEFORE':2,'DURING':5,'AFTER':2}
# Derived household-load plausibility only. Communication errors, SOC faults,
# non-finite values or anything else are NOT closable by this procedure.
ALLOWED_INVALID_REASONS=('home_kw:implausible',)
MAX_INVALID_TOTAL=2
MAX_TRACE_BYTES=8*1024*1024
REQUIRED_SEQUENCE=('SESSION_LATCH_ARMED','DELEGATE_STARTED','DELEGATE_EXIT','POST_HAND_BACK','SESSION_RESULT')

class ClosureHold(RuntimeError): pass

def _now():return dt.datetime.now(dt.timezone.utc)

def _read_regular(path,limit):
    path=pathlib.Path(path)
    if path.is_symlink() or path.parent.is_symlink():raise ClosureHold('symlink not permitted: '+str(path))
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:raise ClosureHold('not a single-link regular file: '+str(path))
        if st.st_size>limit:raise ClosureHold('file too large: '+str(path))
        chunks=[];total=0
        while True:
            b=os.read(fd,65536)
            if not b:break
            total+=len(b)
            if total>limit:raise ClosureHold('file too large: '+str(path))
            chunks.append(b)
        return b''.join(chunks)
    finally:os.close(fd)

def read_latch(path=LATCH):
    raw=_read_regular(path,4095)
    try:value=json.loads(raw)
    except ValueError as exc:raise ClosureHold('latch not valid JSON') from exc
    if value.get('schema')!='SIGEN_RC21_RECOVERY_LATCH' or value.get('state')!='RECOVERY_REQUIRED_UNTIL_VERIFIED':
        raise ClosureHold('unexpected latch schema/state')
    sid=value.get('session_id')
    if not isinstance(sid,str) or not sid.isalnum() or not 8<=len(sid)<=128:raise ClosureHold('invalid latch session id')
    return value,hashlib.sha256(raw).hexdigest()

def trace_path_for(session,data=DATA):
    return pathlib.Path(data)/f'rc27-pilot-{session}.jsonl'

def _reason_allowed(error):
    if not isinstance(error,str) or not error.startswith('SampleError: invalid power sample:'):return False
    detail=error.split(':',2)[2]
    flags=[f.strip(" []'\"") for f in detail.replace(';',',').split(',') if f.strip(" []'\"")]
    return bool(flags) and all(f in ALLOWED_INVALID_REASONS for f in flags)

def review_evidence(session,trace):
    """Pure function over hash-verified trace bytes. Returns (ok, findings)."""
    rows=[]
    for n,line in enumerate(trace.decode('utf-8').splitlines(),1):
        if not line.strip():continue
        try:rows.append(json.loads(line))
        except ValueError:raise ClosureHold(f'trace line {n} unparseable')
    problems=[]
    if any(r.get('schema')!=TRACE_SCHEMA for r in rows):problems.append('FOREIGN_SCHEMA_IN_TRACE')
    events=[r for r in rows if r.get('record_type')=='SESSION_EVENT']
    samples=[r for r in rows if r.get('record_type')=='PLANT_SAMPLE']
    # Required lifecycle: exactly one of each, strictly in this order, all for this session.
    names=[e.get('event') for e in events]
    pos={}
    for name in REQUIRED_SEQUENCE:
        idx=[i for i,n in enumerate(names) if n==name]
        if len(idx)!=1:problems.append(f'EVENT_{name}_COUNT_{len(idx)}');continue
        pos[name]=idx[0]
        if events[idx[0]].get('session_id')!=session:problems.append(f'EVENT_{name}_SESSION_MISMATCH')
    if len(pos)==len(REQUIRED_SEQUENCE) and [pos[n] for n in REQUIRED_SEQUENCE]!=sorted(pos.values()):
        problems.append('EVENT_SEQUENCE_OUT_OF_ORDER')
    if any(e.get('session_id')!=session for e in events):problems.append('FOREIGN_OR_UNATTRIBUTED_EVENT')
    if any(n not in REQUIRED_SEQUENCE for n in names):problems.append('UNEXPECTED_EVENT_IN_TRACE')
    get=lambda n:events[pos[n]] if n in pos else {}
    armed,started,exited,post,res=(get(n) for n in REQUIRED_SEQUENCE)
    if res.get('session_id')!=session:problems.append('RESULT_SESSION_MISMATCH')
    if armed.get('action') not in ('GRID_CHARGE','EXPORT') or res.get('action')!=armed.get('action'):problems.append('ACTION_MISMATCH')
    # Exit-code cross-check: delegate event and result must agree, and both be 0.
    if exited.get('returncode')!=0:problems.append('DELEGATE_EXIT_NONZERO')
    if res.get('live_controller_exit')!=0:problems.append('CONTROLLER_EXIT_NONZERO')
    if exited.get('returncode')!=res.get('live_controller_exit'):problems.append('EXIT_CODE_INCONSISTENT')
    # Handback cross-check: post-handback event and result must agree, and both be True.
    if post.get('plant_ok') is not True:problems.append('POST_HANDBACK_PLANT_NOT_OK')
    if post.get('panel_ok') is not True:problems.append('POST_HANDBACK_PANEL_NOT_OK')
    if post.get('plant_ok')!=res.get('plant_handback_verified') or post.get('panel_ok')!=res.get('panel_restored'):
        problems.append('HANDBACK_RESULT_INCONSISTENT')
    if res.get('delegate_timeout') is not False:problems.append('DELEGATE_TIMEOUT')
    if res.get('observer_error') is not None:problems.append('OBSERVER_ERROR')
    if res.get('plant_handback_verified') is not True:problems.append('SESSION_HANDBACK_NOT_VERIFIED')
    if res.get('panel_restored') is not True:problems.append('PANEL_NOT_RESTORED')
    if res.get('modbus_writes_by_observer')!=0:problems.append('OBSERVER_WRITES_NONZERO')
    if any(str(e.get('event','')).startswith('CRITICAL') for e in events):problems.append('CRITICAL_EVENT_IN_TRACE')
    valid={'BEFORE':0,'DURING':0,'AFTER':0};invalid=[]
    for s in samples:
        ph=s.get('phase')
        if ph not in valid:problems.append('UNKNOWN_PHASE');continue
        if s.get('modbus_writes_by_observer')!=0:problems.append('SAMPLE_WRITES_NONZERO')
        if s.get('valid') is True:valid[ph]+=1
        else:invalid.append({'phase':ph,'timestamp_utc':s.get('timestamp_utc'),'error':s.get('error')})
    for ph,m in MIN_VALID.items():
        if valid[ph]<m:problems.append(f'INSUFFICIENT_VALID_{ph}')
    if len(invalid)>MAX_INVALID_TOTAL:problems.append('TOO_MANY_INVALID_SAMPLES')
    if any(not _reason_allowed(i['error']) for i in invalid):problems.append('NON_ALLOWLISTED_INVALID_REASON')
    if any(i['phase']=='DURING' for i in invalid):problems.append('INVALID_SAMPLE_DURING_ACTUATION')
    findings={'valid_counts':valid,'invalid_samples':invalid,'problems':sorted(set(problems)),
              'session_status_recorded':res.get('status'),
              'evidence_quality':'DEGRADED_ACCEPTABLE' if invalid and not problems else ('COMPLETE' if not problems else 'REJECTED')}
    return not problems,findings

import contextlib
@contextlib.contextmanager
def exclusive_controller_lock(lock_path=LOCK):
    """Take the SAME flock the live controllers use, non-blocking, and hold it.
    While held, no cooperating controller (controller.py / RC28 child) can start."""
    lp=pathlib.Path(lock_path)
    if lp.is_symlink() or lp.parent.is_symlink():raise ClosureHold('lock path is a symlink')
    fd=os.open(lp,os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise ClosureHold('lock path not a regular file')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise ClosureHold('controller lock busy: a controller session may be active') from exc
        yield fd
    finally:
        os.close(fd)  # releases flock

def fresh_plant_recovery(preflight,panel,lock_path=LOCK,readbacks=READBACKS,gap=READBACK_GAP_S,sleep=time.sleep,lock_held=False):
    """Read-only. All readbacks must show handback; panel active; writer lock free
    (probed, for --review) or held by this process (lock_held=True, for --close)."""
    reads=[]
    for i in range(readbacks):
        if i:sleep(gap)
        r=preflight()
        if r.get('modbus_writes')!=0:raise ClosureHold('preflight reported writes')
        reads.append({k:r.get(k) for k in ('timestamp_utc','remote_ems_off','self_consumption','pcs_zero','soc_pct','plant_handback_verified')})
    p=panel('is-active',AUTH_UNIT)
    panel_ok=(p.returncode==0 and p.stdout.strip()=='active')
    if lock_held:
        lock_free=True  # caller holds the exclusive controller lock for the whole transaction
    else:
        lock_free=False
        lp=pathlib.Path(lock_path)
        if lp.is_symlink():raise ClosureHold('lock path is a symlink')
        if lp.exists():
            with lp.open('rb') as fp:
                try:fcntl.flock(fp,fcntl.LOCK_EX|fcntl.LOCK_NB);lock_free=True;fcntl.flock(fp,fcntl.LOCK_UN)
                except BlockingIOError:lock_free=False
        else:lock_free=True
    ok=all(r['plant_handback_verified'] is True and r['remote_ems_off'] is True and r['self_consumption'] is True
           and r['pcs_zero'] is True for r in reads) and panel_ok and lock_free
    return ok,{'readbacks':reads,'panel_active':panel_ok,'controller_lock_free':lock_free,'controller_lock_held_by_closure':bool(lock_held)}

def _write_excl(path,obj):
    path=pathlib.Path(path)
    if path.parent.is_symlink():raise ClosureHold('closure dir symlink')
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o400)
    with os.fdopen(fd,'wb') as f:
        f.write((json.dumps(obj,sort_keys=True,allow_nan=False)+'\n').encode());f.flush();os.fsync(f.fileno())
    d=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(d)
    finally:os.close(d)

def review(*,latch_path=LATCH,data=DATA,closures=CLOSURES,preflight,panel,lock_path=LOCK,sleep=time.sleep,now=_now):
    latch,latch_hash=read_latch(latch_path)
    session=latch['session_id']
    tpath=trace_path_for(session,data)
    trace=_read_regular(tpath,MAX_TRACE_BYTES)
    ev_ok,findings=review_evidence(session,trace)
    plant_ok,plant=fresh_plant_recovery(preflight,panel,lock_path,sleep=sleep)
    t=now()
    rec={'schema':SCHEMA,'record_type':'REVIEW','session_id':session,'reviewed_utc':t.isoformat(),
         'expires_utc':(t+dt.timedelta(seconds=REVIEW_TTL_S)).isoformat(),
         'latch_sha256':latch_hash,'trace_file':str(tpath),'trace_sha256':hashlib.sha256(trace).hexdigest(),
         'evidence_acceptable':ev_ok,'evidence':findings,'plant_recovery_verified':plant_ok,'plant':plant,
         'eligible_for_operator_closure':ev_ok and plant_ok,'modbus_writes':0,
         'physical_delivery_verified':False,'host_loss_recovery_verified':False,'further_pilots_authorised':False}
    _write_excl(pathlib.Path(closures)/f'{session}-review-{t.strftime("%Y%m%dT%H%M%S%fZ")}.json',rec)
    return rec

def _latest_review(closures,session):
    d=pathlib.Path(closures)
    if not d.is_dir() or d.is_symlink():raise ClosureHold('no review records')
    files=sorted(d.glob(f'{session}-review-*.json'))
    if not files:raise ClosureHold('no review for this session; run --review first')
    return json.loads(_read_regular(files[-1],1<<20))

def challenge_text(session):return 'CLEAR RECOVERY LATCH '+session[:12]

def close(*,operator_ack,input_fn=input,is_tty=None,latch_path=LATCH,data=DATA,closures=CLOSURES,
          preflight,panel,lock_path=LOCK,latch_factory=None,sleep=time.sleep,now=_now,operator=None):
    if operator_ack is not True:raise ClosureHold('--operator-ack required')
    if is_tty is None:is_tty=sys.stdin.isatty()
    if is_tty is not True:raise ClosureHold('local interactive TTY required')
    # Exclusive controller lock held from here until after latch removal and
    # audit: no cooperating controller can start between readback and clearance.
    with exclusive_controller_lock(lock_path):
        latch,latch_hash=read_latch(latch_path)
        session=latch['session_id']
        rev=_latest_review(closures,session)
        if rev.get('eligible_for_operator_closure') is not True:raise ClosureHold('latest review not eligible: '+json.dumps(rev.get('evidence',{}).get('problems')))
        t=now()
        if t>dt.datetime.fromisoformat(rev['expires_utc']):raise ClosureHold('review expired; run --review again')
        if rev.get('latch_sha256')!=latch_hash:raise ClosureHold('latch changed since review')
        trace=_read_regular(trace_path_for(session,data),MAX_TRACE_BYTES)
        if hashlib.sha256(trace).hexdigest()!=rev.get('trace_sha256'):raise ClosureHold('trace changed since review')
        print('RC29 LATCH CLOSURE. No plant writes are made by this tool.')
        print('Evidence:',rev['evidence']['evidence_quality'],'invalid:',json.dumps(rev['evidence']['invalid_samples']))
        print('Confirm in MySigen NOW: Remote EMS off, self-consumption, no active charge/export.')
        expected=challenge_text(session)
        print('Type exactly: '+expected,flush=True)
        if input_fn('Witness: ')!=expected:raise ClosureHold('operator challenge not matched')
        # Second, independent fresh readback immediately before clearing.
        plant_ok,plant=fresh_plant_recovery(preflight,panel,lock_path,sleep=sleep,lock_held=True)
        if not plant_ok:raise ClosureHold('fresh plant readback failed at closure: '+json.dumps(plant))
        stamp=now().strftime('%Y%m%dT%H%M%S%fZ')
        record={'schema':SCHEMA,'record_type':'CLOSURE_AUTHORISED','session_id':session,'authorised_utc':now().isoformat(),
                'operator':operator or os.environ.get('SUDO_USER') or os.environ.get('USER'),
                'review_reviewed_utc':rev['reviewed_utc'],'latch_sha256':latch_hash,'trace_sha256':rev['trace_sha256'],
                'evidence_quality':rev['evidence']['evidence_quality'],'invalid_samples':rev['evidence']['invalid_samples'],
                'closure_plant_readback':plant,'operator_witnessed_mysigen':True,'controller_lock_held':True,'modbus_writes':0,
                'basis':'EVIDENCE_REVIEW_ACCEPTED_AND_FRESH_PLANT_HANDBACK_VERIFIED',
                'physical_delivery_verified':False,'host_loss_recovery_verified':False,'further_pilots_authorised':False}
        _write_excl(pathlib.Path(closures)/f'{session}-closure-{stamp}.json',record)
        if latch_factory is None:
            from recovery_latch_rc21 import RecoveryLatch as latch_factory
        lt=latch_factory(pathlib.Path(latch_path))
        lt.clear_after_independent_recovery(session,physical_proof=lambda:plant_ok is True,operator_ack=True)
        done={'schema':SCHEMA,'record_type':'LATCH_CLEARED','session_id':session,'cleared_utc':now().isoformat(),'modbus_writes':0}
        _write_excl(pathlib.Path(closures)/f'{session}-cleared-{stamp}.json',done)
        result={**record,'status':'LATCH_CLEARED_OPERATOR_WITNESSED'}
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description='RC29 operator-witnessed recovery latch closure (read-only plant access)')
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--status',action='store_true',help='show latch only; no plant access')
    g.add_argument('--review',action='store_true',help='read-only evidence review + fresh plant readback')
    g.add_argument('--close',action='store_true',help='operator-witnessed clearance after valid review')
    p.add_argument('--operator-ack',action='store_true')
    a=p.parse_args(argv)
    try:
        if a.status:
            if not LATCH.exists():print(json.dumps({'schema':SCHEMA,'latch':'ABSENT','modbus_writes':0}));return 0
            v,h=read_latch();print(json.dumps({'schema':SCHEMA,'latch':v,'latch_sha256':h,'modbus_writes':0},sort_keys=True));return 0
        from commissioning_preflight_rc18 import inspect
        from controller import systemctl
        if a.review:
            r=review(preflight=inspect,panel=systemctl);print(json.dumps(r,sort_keys=True,indent=1))
            return 0 if r['eligible_for_operator_closure'] else 2
        r=close(operator_ack=a.operator_ack,preflight=inspect,panel=systemctl)
        print(json.dumps(r,sort_keys=True,indent=1));return 0
    except (Exception,KeyboardInterrupt) as exc:
        print('RC29_CLOSURE_HOLD',type(exc).__name__,str(exc),'LATCH_RETAINED MODBUS_WRITES=0',file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
