#!/usr/bin/env python3
"""Phase 3A R7 read-only evidence adapter. Never equate battery-port energy with grid-side energy."""
import argparse, csv, datetime as dt, json, math, os, tempfile
from pathlib import Path
ROOT=Path('/opt/sigenstor/data')
SOURCES=(ROOT/'household_telemetry.json', ROOT/'HouseholdDemand7d.csv')
OUT=ROOT/'rtm/phase3a-telemetry-r7.json'
def timestamp(v):
    if not isinstance(v,str): raise ValueError('timestamp missing')
    t=dt.datetime.fromisoformat(v.replace('Z','+00:00'))
    if t.tzinfo is None: raise ValueError('naive timestamp')
    return t.astimezone(dt.timezone.utc)
def numeric(x):
    if isinstance(x,bool): raise ValueError('boolean measurement')
    v=float(x)
    if not math.isfinite(v): raise ValueError('nonfinite measurement')
    return v
def integrate(points):
    """Battery-port signed kW (+charge/-discharge). Conservative trapezoids; no gap interpolation."""
    parsed=sorted((timestamp(x['timestamp_utc']),numeric(x['battery_kw'])) for x in points)
    if len(parsed)<2: return {'pairs_accepted':0,'pairs_skipped':0,'charge_battery_port_kwh':0.,'discharge_battery_port_kwh':0.}
    if len(set(t for t,p in parsed))!=len(parsed): raise ValueError('duplicate time')
    ch=dis=0.;ok=skipped=0
    for (a,pa),(b,pb) in zip(parsed,parsed[1:]):
        seconds=(b-a).total_seconds()
        if seconds<=0: raise ValueError('nonmonotonic time')
        if seconds>360 or abs(pa)>8.5 or abs(pb)>8.5 or pa*pb<0:
            skipped+=1;continue
        energy=abs(pa+pb)/2*seconds/3600
        if pa>=0:ch+=energy
        else:dis+=energy
        ok+=1
    return {'pairs_accepted':ok,'pairs_skipped':skipped,'charge_battery_port_kwh':round(ch,6),'discharge_battery_port_kwh':round(dis,6)}
def gather_records(value, limit=2000):
    """Accept only explicitly labelled signed battery_kw, never house_kw, grid_kw or SOC as surrogate."""
    if isinstance(value,list): candidates=value
    elif isinstance(value,dict):
        candidates=[]
        for k in ('samples','readings','records','points','telemetry'):
            if isinstance(value.get(k),list): candidates=value[k];break
        if not candidates and 'battery_kw' in value:candidates=[value]
    else: candidates=[]
    records=[]
    for row in candidates[-limit:]:
        if not isinstance(row,dict) or 'battery_kw' not in row:continue
        ts=next((row[k] for k in ('timestamp_utc','timestamp','utc','time_utc') if k in row),None)
        if ts is None:continue
        try:
            p=numeric(row['battery_kw']);t=timestamp(ts)
            if abs(p)>8.5:continue
            records.append({'timestamp_utc':t.isoformat(),'battery_kw':p})
        except (ValueError,TypeError,OverflowError):continue
    return records
def summarize(source,now):
    if source.is_symlink() or not source.is_file():
        return {'source':str(source),'state':'MISSING_OR_UNSAFE'}
    try:
        if source.suffix.lower()=='.json':
            obj=json.loads(source.read_text());records=gather_records(obj)
            keys=sorted(obj.keys())[:30] if isinstance(obj,dict) else []
        else:
            with source.open(newline='') as f:reader=csv.DictReader(f);keys=(reader.fieldnames or [])[:30]
            # Household demand is not battery-side or grid-side battery flow evidence.
            return {'source':str(source),'state':'HOUSEHOLD_DEMAND_ONLY_NOT_BATTERY_FLOW','columns':keys}
        result={'source':str(source),'state':'BATTERY_PORT_ONLY' if records else 'NO_VALID_SIGNED_BATTERY_SAMPLE','field_names':keys,'samples':len(records)}
        if records:
            latest=max(timestamp(p['timestamp_utc']) for p in records)
            result['latest_utc']=latest.isoformat();result['latest_age_seconds']=round((now-latest).total_seconds(),2)
            result['energy']=integrate(records)
        return result
    except (OSError,ValueError,TypeError,KeyError,OverflowError) as e:
        return {'source':str(source),'state':'UNREADABLE_OR_INVALID','error':type(e).__name__}
def build(now,sources=SOURCES):
    items=[summarize(p,now) for p in sources]
    return {'schema':'SIGEN_PHASE3A_TELEMETRY_EVIDENCE_R7','timestamp_utc':now.isoformat(),
      'sources':items,'battery_port_contract':'SIGNED_BATTERY_KW_POSITIVE_CHARGE_NEGATIVE_DISCHARGE',
      'grid_side_energy_contract_verified':False,'physical_setpoint_verified':False,
      'measurement_status':'GRID_SIDE_BATTERY_FLOW_NOT_INDEPENDENTLY_VERIFIED',
      'dispatch_permitted':False,'autonomous_dispatch':False,'modbus_writes':0}
def atomic(path,value):
    if path.is_symlink() or path.parent.is_symlink():raise ValueError('symlink destination')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.phase3a-r7-')
    try:
        with os.fdopen(fd,'w') as f: json.dump(value,f,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
        os.chmod(name,0o644);os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
def main():
    p=argparse.ArgumentParser();p.add_argument('--publish',action='store_true');args=p.parse_args()
    result=build(dt.datetime.now(dt.timezone.utc))
    if args.publish:atomic(OUT,result)
    print(json.dumps(result,sort_keys=True));print('PHASE3A_R7_TELEMETRY_EVIDENCE_NO_MODBUS_WRITES')
if __name__=='__main__':main()
