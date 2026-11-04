#!/usr/bin/env python3
"""Phase 3A R10: read-only, bounded battery-port session-energy reconciliation.
No network access, no inverter control, no automatic dispatch. Data remain battery-side.
"""
import argparse,datetime as dt,json,math,os,sqlite3,tempfile
from pathlib import Path
DB=Path('/opt/sigenstor/data/HouseholdTelemetry.sqlite')
OUT=Path('/opt/sigenstor/data/rtm/phase3a-session-energy-r10.json')
UTC=dt.timezone.utc
MAX_GAP=600

def timestamp(s):
    x=dt.datetime.fromisoformat(str(s).replace('Z','+00:00'))
    if x.tzinfo is None:raise ValueError('timezone required')
    return x.astimezone(UTC)
def number(v,low,high):
    if isinstance(v,bool):raise ValueError('boolean not numeric')
    v=float(v)
    if not math.isfinite(v) or not low<=v<=high:raise ValueError('invalid telemetry value')
    return v

def segments(points,start,end):
    """Integrate linear battery_kw samples clipped to exact session boundaries.
    Returns battery-port charge/discharge; gaps and unmeasured edges are not filled.
    """
    if not start<end:raise ValueError('invalid window')
    window=(end-start).total_seconds(); charge=discharge=covered=0.;accepted=skipped=0
    points=sorted(points,key=lambda x:x[0])
    for (ta,pa),(tb,pb) in zip(points,points[1:]):
        seconds=(tb-ta).total_seconds()
        if seconds<=0 or seconds>MAX_GAP:
            skipped+=1;continue
        left=max(ta,start);right=min(tb,end)
        if left>=right:continue
        a=pa+(pb-pa)*(left-ta).total_seconds()/seconds
        b=pa+(pb-pa)*(right-ta).total_seconds()/seconds
        span=(right-left).total_seconds()
        if a*b<0:
            split=abs(a)/(abs(a)+abs(b))
            charge+=(max(a,0)*span*split+max(b,0)*span*(1-split))/7200
            discharge+=(max(-a,0)*span*split+max(-b,0)*span*(1-split))/7200
        else:
            charge+=(max(a,0)+max(b,0))*span/7200
            discharge+=(max(-a,0)+max(-b,0))*span/7200
        covered+=span;accepted+=1
    return {'battery_port_charge_kwh':round(charge,6),'battery_port_discharge_kwh':round(discharge,6),
            'observed_seconds':round(covered,3),'requested_seconds':round(window,3),
            'coverage_pct':round(100*covered/window,3),'accepted_segments':accepted,'skipped_gaps':skipped}

def query(path,start,end):
    if path.is_symlink() or not path.is_file():raise ValueError('unsafe or missing SQLite source')
    uri=path.resolve().as_uri()+'?mode=ro'
    with sqlite3.connect(uri,uri=True,timeout=5) as con:
        con.execute('PRAGMA query_only=ON')
        rows=con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        names=[]
        for (name,) in rows:
            columns={r[1] for r in con.execute('PRAGMA table_info("'+name.replace('"','""')+'")')}
            if {'timestamp_utc','battery_kw','grid_kw','soc_pct'}<=columns:names.append(name)
        if len(names)!=1:raise ValueError('ambiguous or missing telemetry source')
        table=names[0].replace('"','""')
        # Query with bounded extension to allow interpolation across exact boundaries.
        lo=(start-dt.timedelta(seconds=MAX_GAP)).isoformat().replace('+00:00','Z')
        hi=(end+dt.timedelta(seconds=MAX_GAP)).isoformat().replace('+00:00','Z')
        data=con.execute(f'SELECT timestamp_utc,battery_kw,grid_kw,soc_pct FROM "{table}" WHERE timestamp_utc >= ? AND timestamp_utc <= ? ORDER BY timestamp_utc LIMIT 10000',(lo,hi)).fetchall()
    points=[];bad=0
    for ts,p,g,soc in data:
        try:points.append((timestamp(ts),number(p,-12,12)))
        except (ValueError,TypeError,OverflowError):bad+=1
    return points,bad,names[0]

def evaluate(path,start,end,action,planned_grid_kwh=None,now=None):
    now=now or dt.datetime.now(UTC)
    if action not in ('GRID_CHARGE','EXPORT','HOLD'):raise ValueError('unknown action')
    if end>now+dt.timedelta(seconds=5):raise ValueError('future session not yet measurable')
    if (end-start).total_seconds()>3600 or end<=start:raise ValueError('window must be within 60 minutes')
    if planned_grid_kwh is not None:number(planned_grid_kwh,0,4.0)
    points,bad,table=query(path,start,end)
    result=segments(points,start,end)
    coverage=result['coverage_pct'];state='MEASURED_BATTERY_PORT_COMPLETE' if coverage>=95 and result['accepted_segments']>=2 and bad==0 else 'INCOMPLETE_BATTERY_PORT_EVIDENCE'
    ch=result['battery_port_charge_kwh'];di=result['battery_port_discharge_kwh']
    direction=('AGREES' if action=='GRID_CHARGE' and ch>di and ch>0.01 else
               'AGREES' if action=='EXPORT' and di>ch and di>0.01 else
               'NO_COMMANDED_ACTION' if action=='HOLD' else 'UNCONFIRMED')
    return {'schema':'SIGEN_PHASE3A_SESSION_ENERGY_R10','generated_utc':now.isoformat(),
            'start_utc':start.isoformat(),'end_utc':end.isoformat(),'action':action,
            'requested_grid_side_kwh':planned_grid_kwh,'grid_side_delivered_kwh':None,
            'grid_side_verification':'NOT_AVAILABLE_FROM_BATTERY_PORT_TELEMETRY',
            'battery_port_direction':direction,'measurement_state':state,
            'invalid_samples':bad,'source':str(path),'source_table':table,**result,
            'execution_authorised':False,'physical_setpoint_verified':False,
            'autonomous_dispatch':False,'modbus_writes':0}

def publish(body,path):
    if path.is_symlink():raise ValueError('unsafe output symlink')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.phase3a-r10-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(body,f,sort_keys=True,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o644);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def main():
    p=argparse.ArgumentParser();p.add_argument('--start-utc',required=True);p.add_argument('--end-utc',required=True)
    p.add_argument('--action',required=True,choices=['GRID_CHARGE','EXPORT','HOLD']);p.add_argument('--planned-grid-kwh',type=float)
    p.add_argument('--db',type=Path,default=DB);p.add_argument('--out',type=Path,default=OUT);p.add_argument('--publish',action='store_true')
    a=p.parse_args()
    try:
        body=evaluate(a.db,timestamp(a.start_utc),timestamp(a.end_utc),a.action,a.planned_grid_kwh)
        if a.publish:publish(body,a.out)
        print(json.dumps(body,sort_keys=True));print('PHASE3A_R10_SESSION_ENERGY_READ_ONLY_NO_MODBUS_WRITES')
    except Exception as exc:
        print('PHASE3A_R10_BLOCKED',type(exc).__name__,str(exc),'NO_MODBUS_WRITES');raise SystemExit(2)
if __name__=='__main__':main()
