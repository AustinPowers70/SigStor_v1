#!/usr/bin/env python3
"""Read-only evidence journal for operator-supervised commissioning preparation.

No Modbus imports, writes, service control or autonomous scheduling.
This records OBSERVATIONS, not verification of grid-side delivered battery energy.
"""
import argparse, datetime as dt, json, os, pathlib, stat, sys

class EvidenceError(RuntimeError): pass

def utc(value):
    parsed=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:raise EvidenceError('timestamp must include timezone')
    return parsed.astimezone(dt.timezone.utc)

def classify(sample, observed_now, max_age_s=10.0):
    if not isinstance(sample,dict):raise EvidenceError('sample must be object')
    if sample.get('valid') is not True:raise EvidenceError('invalid telemetry')
    stamp=utc(sample['observed_utc']); now=utc(observed_now)
    age=(now-stamp).total_seconds()
    if age < -4 or age > max_age_s:raise EvidenceError('stale/future telemetry')
    soc=float(sample['soc_pct']); battery=float(sample['battery_kw'])
    import math
    if not all(map(math.isfinite,(soc,battery))) or not 0<=soc<=100:raise EvidenceError('invalid numeric telemetry')
    return {'observed_utc':stamp.isoformat(),'age_seconds':round(age,3),'soc_pct':soc,
            'battery_kw':battery,'valid':True,'energy_boundary':'BATTERY_PORT_ONLY',
            'grid_side_battery_energy_verified':False,'modbus_writes':0}

def append_jsonl(path, record):
    path=pathlib.Path(path)
    if path.exists() and (path.is_symlink() or not path.is_file()):raise EvidenceError('unsafe output path')
    if path.parent.is_symlink():raise EvidenceError('unsafe output parent')
    # Fail closed on existing symlink and avoid truncating prior evidence.
    flags=os.O_WRONLY|os.O_APPEND|os.O_CREAT|getattr(os,'O_NOFOLLOW',0)
    fd=os.open(path,flags,0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise EvidenceError('not regular output')
        payload=(json.dumps(record,sort_keys=True,allow_nan=False,separators=(',',':'))+'\n').encode()
        os.write(fd,payload);os.fsync(fd)
    finally:os.close(fd)

def main(argv=None):
    p=argparse.ArgumentParser(description='RC6 read-only battery-port evidence recorder')
    p.add_argument('--sample-json',type=pathlib.Path)
    p.add_argument('--out',type=pathlib.Path)
    p.add_argument('--execute-slot',action='store_true')
    a=p.parse_args(argv)
    if a.execute_slot:
        print('BLOCKED: RC6 has no production full-slot actuator; MODBUS_WRITES=0');return 2
    if a.sample_json is None or a.out is None:
        p.print_help();return 0
    try:
        if a.sample_json.is_symlink():raise EvidenceError('unsafe sample source')
        sample=json.loads(a.sample_json.read_text())
        now=dt.datetime.now(dt.timezone.utc).isoformat()
        record=classify(sample,now)
        append_jsonl(a.out,record)
        print(json.dumps({'status':'BATTERY_PORT_OBSERVATION_RECORDED','modbus_writes':0,
            'grid_side_battery_energy_verified':False},sort_keys=True))
        return 0
    except (OSError,KeyError,ValueError,TypeError,EvidenceError) as exc:
        print('PHASE3B_RC6_FAIL_CLOSED',type(exc).__name__,str(exc),'MODBUS_WRITES=0');return 2
if __name__=='__main__':sys.exit(main())
