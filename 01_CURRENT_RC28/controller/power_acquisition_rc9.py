#!/usr/bin/env python3
"""RC9 bounded *read-only* live FC04 grid/battery/PV/SOC sampling.

Uses unchanged commissioned v4.4.6.5 FC04 reader. No controller imports.
Aggregate grid power is NOT battery-attributable grid-side energy.
"""
import argparse,datetime as dt,importlib.util,json,math,os,pathlib,stat,sys,time

HERE=pathlib.Path(__file__).resolve().parent
SOURCE=HERE.parent/'accepted'/'telemetry'/'sigen_telemetry_v4_4_6_5.py'
HOST='192.168.0.8'; PORT=502; UNIT=247; ADDRESS=30005
SCHEMA='SIGEN_PHASE3B_RC9_POWER_SAMPLE_V1'
class SampleError(ValueError): pass

def original_reader():
    if not SOURCE.is_file(): raise SampleError('validated decoder not bundled')
    spec=importlib.util.spec_from_file_location('sigen_telemetry_legacy_rc9', SOURCE)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def sample_once(reader=None):
    legacy=reader or original_reader()
    data=legacy.read_plant(HOST,PORT,UNIT,2.0,ADDRESS)
    data=legacy.validate_sample(data,12.0)
    if not data['valid']:
        raise SampleError('invalid power sample: '+str(data.get('issues','')))
    for key in ('soc_pct','battery_kw','grid_kw','pv_kw','home_kw'):
        if isinstance(data[key],bool) or not math.isfinite(float(data[key])): raise SampleError('non-finite reading')
    return {key:float(data[key]) for key in ('soc_pct','battery_kw','grid_kw','pv_kw','home_kw')}

def append(path,row):
    path=pathlib.Path(path)
    if path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink(): raise SampleError('unsafe journal path')
    fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode): raise SampleError('journal not regular file')
        b=(json.dumps(row,sort_keys=True,allow_nan=False)+'\n').encode()
        if os.write(fd,b)!=len(b):raise SampleError('short journal write')
        os.fsync(fd)
    finally:os.close(fd)

def run(duration,interval,path,read=sample_once,clock=time.monotonic,sleep=time.sleep,utc=None,writer=append):
    if isinstance(duration,bool) or isinstance(interval,bool) or not 1<=duration<=1800 or not 1<=interval<=10:raise SampleError('sampling bounds')
    utc=utc or (lambda:dt.datetime.now(dt.timezone.utc))
    start=clock();deadline=start+duration; samples=failures=0; previous=None
    while clock()<deadline:
        before=clock();timestamp=utc()
        if timestamp.tzinfo is None:raise SampleError('UTC timestamp missing offset')
        values={};error=None
        try:values=read()
        except (ValueError,OSError,RuntimeError,TypeError,KeyError) as exc:
            error=type(exc).__name__;failures+=1
        row={'schema':SCHEMA,'timestamp_utc':timestamp.astimezone(dt.timezone.utc).isoformat(),
             'valid':error is None,'error':error,'energy_boundary':'BATTERY_PORT_AND_AGGREGATE_GRID_ONLY',
             'battery_grid_side_delivery_verified':False,'modbus_writes':0,
             'soc_pct':None,'battery_kw':None,'grid_kw':None,'pv_kw':None,'home_kw':None}
        if error is None:
            for key in ('soc_pct','battery_kw','grid_kw','pv_kw','home_kw'):
                val=values[key]
                if isinstance(val,bool) or not math.isfinite(float(val)):raise SampleError('invalid reader values')
                row[key]=float(val)
        writer(path,row);samples+=1
        after=clock()
        if after<before or (previous is not None and after<previous):raise SampleError('clock regression')
        previous=after
        remaining=deadline-after
        if remaining<=0:break
        # Start-to-start cadence bounded by session deadline.
        sleep(min(remaining,max(0.0,interval-(after-before))))
    return {'schema':'SIGEN_PHASE3B_RC9_POWER_ACQUISITION','status':'COMPLETE' if failures==0 else 'INCOMPLETE_INVALID_READS',
            'samples':samples,'failed_reads':failures,'battery_grid_side_delivery_verified':False,
            'autonomous_dispatch':False,'modbus_writes':0}

def main(argv=None):
    p=argparse.ArgumentParser(description='Read-only bounded FC04 power sampler; no actuation')
    p.add_argument('--seconds',type=int,default=30)
    p.add_argument('--interval-seconds',type=float,default=2.0)
    p.add_argument('--out',type=pathlib.Path,default=pathlib.Path('/opt/sigenstor/data/rtm/phase3b-rc9-power.jsonl'))
    p.add_argument('--execute-slot',action='store_true')
    args=p.parse_args(argv)
    if args.execute_slot:
        print('BLOCKED: RC9 cannot actuate; MODBUS_WRITES=0');return 2
    try:
        result=run(args.seconds,args.interval_seconds,args.out)
        print(json.dumps(result,sort_keys=True));return 0 if result['failed_reads']==0 else 2
    except (OSError,ValueError,TypeError,KeyError) as exc:
        print('PHASE3B_RC9_FAIL_CLOSED',type(exc).__name__,str(exc),'MODBUS_WRITES=0');return 2
if __name__=='__main__':sys.exit(main())
