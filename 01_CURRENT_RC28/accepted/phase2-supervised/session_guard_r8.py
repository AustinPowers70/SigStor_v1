#!/usr/bin/env python3
"""R8 durable, observation-only execution state projection. No network or plant access."""
import argparse, datetime as dt, json, os, tempfile, fcntl
from pathlib import Path
ROOT=Path('/opt/sigenstor/data/rtm')
R7=ROOT/'phase2-operational-r7.json'
AUDIT=ROOT/'phase1-supervised-audit.jsonl'
OUTPUT=ROOT/'phase2-session-r8.json'
LOCK=ROOT/'.phase2-r8.lock'
STARTS={'CHARGE_STARTED':'CHARGE', 'EXPORT_PILOT_STARTED':'EXPORT', 'OPERATOR_REQUESTED_CHARGE':'CHARGE', 'OPERATOR_REQUESTED_EXPORT':'EXPORT'}
ENDS={'HANDBACK_VERIFIED':'CHARGE','EXPORT_HANDBACK_VERIFIED':'EXPORT'}
CRITICAL={'CRITICAL_HANDBACK_UNVERIFIED','CRITICAL_EXPORT_HANDBACK_UNVERIFIED','CRITICAL_AUTHORITY_RESTART_WITHHELD','CRITICAL_AUTHORITY_RESTART_FAILED'}
UTC=dt.timezone.utc

def timestamp(value):
    v=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if v.tzinfo is None:raise ValueError('timezone missing')
    return v.astimezone(UTC)

def project(status, lines, now):
    issues=[]; events=[]
    if status.get('schema')!='SIGEN_PHASE2_OPERATIONAL_R7':issues.append('R7_SCHEMA_INVALID')
    if status.get('dispatch_enabled') is not False or status.get('plant_writes')!=0:issues.append('R7_DISPATCH_STATE_UNSAFE')
    try:
        age=(now-timestamp(status['timestamp_utc'])).total_seconds()
        if age < -120 or age>180:issues.append('R7_STALE_OR_FUTURE')
    except (KeyError,ValueError,TypeError):issues.append('R7_TIMESTAMP_INVALID');age=None
    if status.get('state')!='PASSIVE_HEALTHY':issues.append('R7_NOT_HEALTHY')
    for line in lines:
        try:
            rec=json.loads(line); stamp=timestamp(rec['timestamp']); event=rec['event']
            if not isinstance(event,str):continue
            events.append((stamp,event))
        except (ValueError,KeyError,TypeError):
            issues.append('AUDIT_LINE_UNREADABLE')
    events.sort(key=lambda v:v[0])
    active=None;last_success=None;last_event=None
    for stamp,event in events:
        last_event={'timestamp_utc':stamp.isoformat(),'event':event}
        if event in STARTS:
            if active and (stamp-active['timestamp']).total_seconds()<180:issues.append('OVERLAPPING_OPERATION_EVENTS')
            active={'kind':STARTS[event],'timestamp':stamp,'start_event':event}
        elif event in ENDS:
            if active and active['kind']==ENDS[event]:
                last_success={'kind':active['kind'],'start_utc':active['timestamp'].isoformat(),'verified_utc':stamp.isoformat()}
                active=None
            else:issues.append('UNMATCHED_HANDBACK_EVENT')
        elif event in CRITICAL:
            issues.append('CRITICAL_AUDIT_EVENT')
    # Historical critical records remain visible; do not automatically treat old cleared faults as newly active.
    if active:
        elapsed=(now-active['timestamp']).total_seconds()
        if elapsed>120:issues.append('UNRESOLVED_OPERATION_EVENT')
    return {'schema':'SIGEN_PHASE2_SESSION_R8','timestamp_utc':now.isoformat(), 'mode':'PASSIVE_SESSION_OBSERVER',
            'dispatch_enabled':False,'plant_writes':0,'r7_age_seconds':round(age,2) if age is not None else None,
            'state':'ATTENTION_REQUIRED' if issues else ('OBSERVED_OPERATION_IN_PROGRESS' if active else 'PASSIVE_READY'),
            'reasons':sorted(set(issues)), 'audit_events_seen':len(events),
            'unresolved_operation':({'kind':active['kind'],'start_utc':active['timestamp'].isoformat()} if active else None),
            'last_verified_handback':last_success,'latest_audit_event':last_event,
            'recovery':'OPERATOR_ACTION_ONLY_NO_PLANT_WRITES'}

def atomic_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=str(path.parent),prefix='.r8-')
    try:
        with os.fdopen(fd,'w') as f:json.dump(data,f,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
        os.chmod(name,0o640);os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def main():
    p=argparse.ArgumentParser();p.add_argument('--status',action='store_true');args=p.parse_args()
    if args.status:
        print(OUTPUT.read_text() if OUTPUT.exists() else 'R8_STATUS_NOT_PUBLISHED');return
    ROOT.mkdir(parents=True,exist_ok=True)
    with LOCK.open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:status=json.loads(R7.read_text())
        except (OSError,ValueError):status={'state':'UNAVAILABLE'}
        try:lines=AUDIT.read_text().splitlines()[-5000:]
        except OSError:lines=[]
        result=project(status,lines,dt.datetime.now(UTC))
        atomic_json(OUTPUT,result)
    print(json.dumps(result,sort_keys=True))
    print('PHASE2_R8_PASSIVE_SESSION_PUBLISHED_NO_MODBUS_WRITES')
if __name__=='__main__':main()
