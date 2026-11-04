#!/usr/bin/env python3
"""R12 durable supervised execution intent ledger. Strictly read-only; no plant dispatch.
State machine: PROPOSED -> APPROVED -> CLOSED, or EXPIRED/ABORTED.
APPROVED is an operator planning acknowledgement, NOT authorization for inverter writes.
"""
import argparse, datetime as dt, json, os, sqlite3, sys, uuid
from pathlib import Path
DB=Path('/opt/sigenstor/data/rtm/phase2-sessions-r12.sqlite3')
PUBLIC=Path('/opt/sigenstor/data/rtm/phase2-session-status-r12.json')
MAX_AGE=60

def now_utc(): return dt.datetime.now(dt.timezone.utc)
def parse_utc(s):
    value=dt.datetime.fromisoformat(s.replace('Z','+00:00'))
    if value.tzinfo is None: raise ValueError('timezone required')
    return value.astimezone(dt.timezone.utc)
def connect(db=DB):
    db.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(db,timeout=10,isolation_level=None)
    con.execute('PRAGMA busy_timeout=10000')
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA synchronous=FULL')
    con.executescript('''CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, window_utc TEXT NOT NULL, created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('GRID_CHARGE','EXPORT')), energy_kwh REAL NOT NULL CHECK(energy_kwh>=0.025), status TEXT NOT NULL CHECK(status IN ('PROPOSED','APPROVED','CLOSED','EXPIRED','ABORTED')), reason TEXT NOT NULL); CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,utc TEXT NOT NULL,event TEXT NOT NULL,detail TEXT NOT NULL);''')
    return con

def reconcile(con,now=None):
    now=now or now_utc(); expired=[]
    con.execute('BEGIN IMMEDIATE')
    try:
        rows=con.execute("SELECT id,window_utc,status FROM sessions WHERE status IN ('PROPOSED','APPROVED')").fetchall()
        for sid,window,status in rows:
            if now >= parse_utc(window)+dt.timedelta(minutes=30):
                con.execute("UPDATE sessions SET status='EXPIRED',updated_utc=?,reason=? WHERE id=?",(now.isoformat(),'WINDOW_ELAPSED_NO_PLANT_DISPATCH',sid))
                con.execute('INSERT INTO events(session_id,utc,event,detail) VALUES(?,?,?,?)',(sid,now.isoformat(),'EXPIRED',status))
                expired.append(sid)
        con.execute('COMMIT')
    except BaseException:
        con.execute('ROLLBACK');raise
    return expired

def candidate():
    root=Path('/opt/sigenstor/scripts/phase2-supervised')
    path=root/'scheduled.py'
    if not path.is_file() or path.is_symlink(): raise RuntimeError('R4 source unavailable')
    sys.path.insert(0,str(root))
    try:
        from scheduled import decision
        out=decision()
    finally:sys.path.remove(str(root))
    if not out.get('eligible') or out.get('decision') not in ('EXPORT','GRID_CHARGE'):
        raise RuntimeError('NO_QUALIFIED_RC13_ACTIVE_WINDOW: '+str(out.get('decision')))
    start=parse_utc(out['start_utc'])
    if not start<=now_utc()<start+dt.timedelta(minutes=30):raise RuntimeError('RC13 window no longer active')
    return out,start

def propose(con,selection=None,now=None):
    out,start=selection if selection else candidate()
    at=now or now_utc()
    if not start<=at<start+dt.timedelta(minutes=30):raise RuntimeError('window not active')
    if not out.get('eligible') or out.get('decision') not in ('GRID_CHARGE','EXPORT'):raise RuntimeError('not eligible')
    energy=out.get('scheduled_energy_kwh')
    if type(energy) not in (int,float) or not 0.025<=energy<=100:raise RuntimeError('invalid planned energy')
    sid=str(uuid.uuid4())
    con.execute('BEGIN IMMEDIATE')
    try:
        if con.execute("SELECT 1 FROM sessions WHERE status IN ('PROPOSED','APPROVED') LIMIT 1").fetchone():raise RuntimeError('active intent exists')
        con.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)',(sid,start.isoformat(),at.isoformat(),at.isoformat(),out['decision'],energy,'PROPOSED','READ_ONLY_INTENT'))
        con.execute('INSERT INTO events(session_id,utc,event,detail) VALUES(?,?,?,?)',(sid,at.isoformat(),'PROPOSED','NO_MODBUS_DISPATCH'))
        con.execute('COMMIT')
    except BaseException:con.execute('ROLLBACK');raise
    return sid

def transition(con,sid,dest,reason,at=None):
    at=at or now_utc()
    allowed={'APPROVED':('PROPOSED',),'ABORTED':('PROPOSED','APPROVED'),'CLOSED':('APPROVED',)}
    if dest not in allowed:raise ValueError('invalid transition')
    con.execute('BEGIN IMMEDIATE')
    try:
        row=con.execute('SELECT status,window_utc FROM sessions WHERE id=?',(sid,)).fetchone()
        if not row or row[0] not in allowed[dest]:raise RuntimeError('invalid session transition')
        if dest=='APPROVED' and at>=parse_utc(row[1])+dt.timedelta(minutes=30):raise RuntimeError('expired window')
        con.execute('UPDATE sessions SET status=?,reason=?,updated_utc=? WHERE id=?',(dest,reason,at.isoformat(),sid))
        con.execute('INSERT INTO events(session_id,utc,event,detail) VALUES(?,?,?,?)',(sid,at.isoformat(),dest,reason))
        con.execute('COMMIT')
    except BaseException:con.execute('ROLLBACK');raise

def snapshot(con):
    rows=con.execute('SELECT id,window_utc,kind,energy_kwh,status,reason,updated_utc FROM sessions ORDER BY created_utc DESC LIMIT 10').fetchall()
    active=[r for r in rows if r[4] in ('PROPOSED','APPROVED')]
    return {'schema':'SIGEN_PHASE2_SESSION_R12','timestamp_utc':now_utc().isoformat(),'economic_model':'RC13_FROZEN','mode':'SUPERVISED_INTENT_ONLY','dispatch_enabled':False,'modbus_writes':0,'active_intents':len(active),'recent_sessions':[dict(zip(('id','window_utc','kind','energy_kwh','status','reason','updated_utc'),r)) for r in rows]}

def publish(obj,path=PUBLIC):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise RuntimeError('unsafe symlink target')
    import tempfile
    fd,tmp=tempfile.mkstemp(prefix='.phase2-r12-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(obj,f,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o644);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def main(argv=None):
    p=argparse.ArgumentParser(description='R12 operator intent ledger: never commands inverter')
    g=p.add_mutually_exclusive_group(required=True)
    for cmd in ('status','propose','approve','abort','close'):g.add_argument('--'+cmd,action='store_true')
    p.add_argument('--id');p.add_argument('--operator-ack',action='store_true')
    args=p.parse_args(argv)
    with connect() as con:
        reconcile(con)
        if args.propose: print('R12_PROPOSED',propose(con))
        if args.approve or args.abort or args.close:
            if not args.id:raise RuntimeError('--id required')
            if args.approve and (not args.operator_ack or not sys.stdin.isatty()):raise RuntimeError('interactive operator acknowledgement required')
            dest='APPROVED' if args.approve else 'ABORTED' if args.abort else 'CLOSED'
            transition(con,args.id,dest,'OPERATOR_INTENT_ONLY_NO_PLANT_DISPATCH')
        out=snapshot(con);publish(out);print(json.dumps(out,sort_keys=True))
    return 0
if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:print('R12_BLOCKED',str(e),file=sys.stderr);sys.exit(2)
