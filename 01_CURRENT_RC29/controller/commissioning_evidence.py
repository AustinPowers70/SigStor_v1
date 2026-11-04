#!/usr/bin/env python3
"""Read-only session evidence assessor; never infers battery-to-grid allocation."""
import argparse, datetime as dt, json, math, pathlib, sqlite3, sys
UTC=dt.timezone.utc
class EvidenceQualityError(ValueError): pass

def stamp(value):
    result=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if result.tzinfo is None:raise EvidenceQualityError('timezone required')
    return result.astimezone(UTC)

def finite(v):
    if isinstance(v,bool):raise EvidenceQualityError('boolean numeric')
    v=float(v)
    if not math.isfinite(v):raise EvidenceQualityError('nonfinite numeric')
    return v

def assess(rows,start,end,action,max_gap_s=10,minimum_samples=3):
    start,end=stamp(start),stamp(end)
    if end<=start or (end-start).total_seconds()>3600:raise EvidenceQualityError('invalid session window')
    if action not in ('GRID_CHARGE','EXPORT'):raise EvidenceQualityError('unknown action')
    if not 0<max_gap_s<=30 or minimum_samples<2:raise EvidenceQualityError('invalid sampling policy')
    accepted=[];invalid=0;future=0
    for row in rows:
        try:
            t=stamp(row['timestamp_utc']);b=finite(row['battery_kw']);g=finite(row['grid_kw']);s=finite(row['soc_pct'])
            if not 0<=s<=100 or abs(b)>12 or abs(g)>20:raise EvidenceQualityError('telemetry range')
            if t>end: future+=1;continue
            if start<=t<=end:accepted.append((t,b,g,s))
        except (ValueError,TypeError,KeyError,OverflowError):invalid+=1
    accepted.sort(key=lambda x:x[0]); unique=[];dup=0
    for point in accepted:
        if unique and point[0]==unique[-1][0]:dup+=1;continue
        unique.append(point)
    gaps=[(b[0]-a[0]).total_seconds() for a,b in zip(unique,unique[1:])]
    in_coverage=sum(g for g in gaps if g<=max_gap_s)
    duration=(end-start).total_seconds()
    missing_edges=(unique[0][0]-start).total_seconds()+(end-unique[-1][0]).total_seconds() if unique else duration
    max_gap=max([*gaps,missing_edges] or [duration])
    # Integrate only consecutive actual samples; no interpolation across telemetry gaps.
    charge=discharge=grid_import=grid_export=0.
    for a,b in zip(unique,unique[1:]):
        sec=(b[0]-a[0]).total_seconds()
        if not 0<sec<=max_gap_s:continue
        # Trapezoidal energies; conservative without evidence of load allocation.
        for x,y,add_pos,add_neg in [(a[1],b[1],'battery','battery'),(a[2],b[2],'grid','grid')]:
            if x*y<0:
                split=abs(x)/(abs(x)+abs(y));pos=(max(x,0)*split+max(y,0)*(1-split))*sec/7200
                neg=(max(-x,0)*split+max(-y,0)*(1-split))*sec/7200
            else:
                pos=(max(x,0)+max(y,0))*sec/7200;neg=(max(-x,0)+max(-y,0))*sec/7200
            if add_pos=='battery':charge+=pos;discharge+=neg
            else:grid_import+=pos;grid_export+=neg
    # Edges must also be observed, not merely interpolated into full coverage.
    edge_ok=bool(unique) and (unique[0][0]-start).total_seconds()<=max_gap_s and (end-unique[-1][0]).total_seconds()<=max_gap_s
    dense= len(unique)>=minimum_samples and not invalid and not dup and not future and edge_ok and all(g<=max_gap_s for g in gaps)
    battery_direction=('CHARGE' if charge>discharge else 'DISCHARGE' if discharge>charge else 'UNKNOWN')
    expected='CHARGE' if action=='GRID_CHARGE' else 'DISCHARGE'
    return {'schema':'SIGEN_PHASE3B_COMMISSIONING_EVIDENCE_V1','action':action,'actual_in_session_samples':len(unique),
            'invalid_rows':invalid,'duplicate_timestamps':dup,'out_of_window_future_rows':future,
            'max_gap_seconds':round(max_gap,3),'edge_observed':edge_ok,'dense_samples_verified':dense,
            'observed_intervals_seconds':round(in_coverage,3),'window_seconds':round(duration,3),
            'battery_port_charge_kwh':round(charge,6),'battery_port_discharge_kwh':round(discharge,6),
            'aggregate_grid_import_kwh':round(grid_import,6),'aggregate_grid_export_kwh':round(grid_export,6),
            'battery_port_direction':battery_direction,'battery_port_direction_agrees':battery_direction==expected and dense,
            'battery_grid_side_delivery_verified':False,'meter_battery_allocation_verified':False,
            'commissioning_evidence_ready':dense and battery_direction==expected,
            'autonomous_dispatch':False,'modbus_writes':0,
            'qualification':'BATTERY_PORT_DIRECTION_ONLY' if dense and battery_direction==expected else 'INSUFFICIENT_IN_SESSION_EVIDENCE'}

def from_sqlite(path,start,end):
    path=pathlib.Path(path)
    if path.is_symlink() or not path.is_file():raise EvidenceQualityError('unsafe or missing database')
    uri=path.resolve().as_uri()+'?mode=ro'
    with sqlite3.connect(uri,uri=True,timeout=5) as con:
        con.execute('PRAGMA query_only=ON')
        names=[]
        for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            cols={c[1] for c in con.execute('PRAGMA table_info("'+name.replace('"','""')+'")')}
            if {'timestamp_utc','battery_kw','grid_kw','soc_pct'}<=cols:names.append(name)
        if len(names)!=1:raise EvidenceQualityError('ambiguous telemetry table')
        table=names[0].replace('"','""')
        return [dict(zip(('timestamp_utc','battery_kw','grid_kw','soc_pct'),r)) for r in con.execute(
            f'SELECT timestamp_utc,battery_kw,grid_kw,soc_pct FROM "{table}" ORDER BY timestamp_utc DESC LIMIT 10000')
            if start<=stamp(r[0])<=end]

def main(argv=None):
    p=argparse.ArgumentParser(description='Read-only Phase 3B session evidence assessment')
    p.add_argument('--db',default='/opt/sigenstor/data/HouseholdTelemetry.sqlite')
    p.add_argument('--start-utc',required=True);p.add_argument('--end-utc',required=True)
    p.add_argument('--action',required=True,choices=['GRID_CHARGE','EXPORT'])
    p.add_argument('--max-gap-seconds',type=float,default=10)
    args=p.parse_args(argv)
    try:
        result=assess(from_sqlite(args.db,stamp(args.start_utc),stamp(args.end_utc)),args.start_utc,args.end_utc,args.action,args.max_gap_seconds)
        print(json.dumps(result,sort_keys=True));return 0
    except (ValueError,TypeError,KeyError,OSError,sqlite3.Error) as exc:
        print('PHASE3B_RC7_EVIDENCE_FAIL_CLOSED',type(exc).__name__,str(exc),'MODBUS_WRITES=0');return 2
if __name__=='__main__':sys.exit(main())
