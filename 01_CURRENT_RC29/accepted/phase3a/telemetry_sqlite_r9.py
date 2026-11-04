#!/usr/bin/env python3
"""Phase3A R9: read-only signed battery-port evidence from existing telemetry SQLite.
Never infer grid-to/from-battery energy from aggregate grid_kw.
"""
import argparse, datetime as dt, json, math, os, sqlite3, tempfile
from pathlib import Path

DB = Path('/opt/sigenstor/data/HouseholdTelemetry.sqlite')
OUT = Path('/opt/sigenstor/data/rtm/phase3a-telemetry-r9.json')
MAX_GAP_S = 600

def stamp(value):
    t=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if t.tzinfo is None: raise ValueError('timestamp lacks timezone')
    return t.astimezone(dt.timezone.utc)

def numeric(v,lo,hi):
    x=float(v)
    if not math.isfinite(x) or not lo<=x<=hi: raise ValueError('out of range')
    return x

def collect(path=DB, now=None, hours=24):
    now=now or dt.datetime.now(dt.timezone.utc)
    now=now.astimezone(dt.timezone.utc)
    if path.is_symlink() or not path.is_file(): raise ValueError('telemetry database missing or symlink')
    uri=path.resolve().as_uri()+'?mode=ro&immutable=0'
    with sqlite3.connect(uri,uri=True,timeout=5) as db:
        db.execute('PRAGMA query_only=ON')
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        candidates=[]
        for table in tables:
            cols={r[1] for r in db.execute('PRAGMA table_info("'+table.replace('"','""')+'")')}
            required={'timestamp_utc','battery_kw','grid_kw','soc_pct'}
            if required <= cols: candidates.append(table)
        if len(candidates)!=1: raise ValueError('telemetry table ambiguous or missing '+str(candidates))
        table=candidates[0].replace('"','""')
        start=now-dt.timedelta(hours=hours)
        # Fetch limited timestamp range with a single prior sample for boundary context.
        query=f'SELECT timestamp_utc,battery_kw,grid_kw,soc_pct FROM "{table}" WHERE timestamp_utc >= ? AND timestamp_utc <= ? ORDER BY timestamp_utc LIMIT 50000'
        raw=list(db.execute(query,(start.isoformat().replace('+00:00','Z'),(now+dt.timedelta(minutes=2)).isoformat().replace('+00:00','Z'))))
    points=[]; invalid=0; future=0
    for ts,battery,grid,soc in raw:
        try:
            t=stamp(ts)
            if t>now+dt.timedelta(seconds=120): future+=1;continue
            b=numeric(battery,-12,12); g=numeric(grid,-20,20);s=numeric(soc,0,100)
            points.append((t,b,g,s))
        except (ValueError,TypeError,OverflowError): invalid+=1
    points.sort(key=lambda x:x[0]);energy_in=energy_out=duration=0.;segments=0;gaps=0
    for a,b in zip(points,points[1:]):
        seconds=(b[0]-a[0]).total_seconds()
        if not 0<seconds<=MAX_GAP_S: gaps+=1;continue
        # Integrate charge/discharge portions independently (positive charge).
        # A crossing is split at the zero crossing, avoiding sign cancellation.
        x,y=a[1],b[1]
        if x*y<0:
            frac=abs(x)/(abs(x)+abs(y)); pos=(max(x,0)*seconds*frac/2+max(y,0)*seconds*(1-frac)/2)/3600
            neg=(max(-x,0)*seconds*frac/2+max(-y,0)*seconds*(1-frac)/2)/3600
        else:
            pos=seconds*(max(x,0)+max(y,0))/7200
            neg=seconds*(max(-x,0)+max(-y,0))/7200
        energy_in+=pos;energy_out+=neg;duration+=seconds;segments+=1
    last=points[-1] if points else None
    age=(now-last[0]).total_seconds() if last else None
    state='BATTERY_PORT_EVIDENCE_READY' if segments and age is not None and 0<=age<=900 else 'INSUFFICIENT_OR_STALE_TELEMETRY'
    return {'schema':'SIGEN_PHASE3A_TELEMETRY_SQLITE_R9','created_utc':now.isoformat(),
            'source':str(path),'source_table':candidates[0], 'sample_count':len(points),
            'invalid_samples':invalid,'future_samples':future,'accepted_segments':segments,
            'skipped_gaps':gaps,'integrated_duration_minutes':round(duration/60,3),
            'battery_port_charge_kwh':round(energy_in,6),'battery_port_discharge_kwh':round(energy_out,6),
            'latest_sample_utc':last[0].isoformat() if last else None,
            'latest_battery_kw':last[1] if last else None,'latest_grid_kw':last[2] if last else None,
            'latest_soc_percent':last[3] if last else None,'latest_sample_age_seconds':round(age,2) if age is not None else None,
            'state':state,'battery_sign':'POSITIVE_CHARGE_NEGATIVE_DISCHARGE',
            'energy_boundary':'BATTERY_PORT_ONLY_NOT_INDEPENDENT_GRID_SIDE_BATTERY_ENERGY',
            'rc13_grid_side_contract':'VERIFIED_SEPARATELY_R5',
            'physical_setpoint_verified':False,'execution_authorised':False,
            'autonomous_dispatch':False,'modbus_writes':0}

def publish(obj,path=OUT):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.phase3a-r9-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(obj,f,sort_keys=True,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o644);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def main():
    p=argparse.ArgumentParser();p.add_argument('--publish',action='store_true');p.add_argument('--db',type=Path,default=DB);args=p.parse_args()
    result=collect(args.db)
    if args.publish:publish(result)
    print(json.dumps(result,sort_keys=True))
    print('PHASE3A_R9_TELEMETRY_SQLITE_EVIDENCE_NO_MODBUS_WRITES')
if __name__=='__main__':main()
