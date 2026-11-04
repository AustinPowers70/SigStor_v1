#!/usr/bin/env python3
"""Bounded read-only FC04 SOC polling. NOT grid/battery power telemetry or an actuator."""
import argparse,datetime as dt,json,os,pathlib,socket,stat,struct,sys,time
HOST='192.168.0.8';PORT=502;UNIT=247;ADDRESS=30005;COUNT=34
class AcquisitionError(ValueError):pass

def recv_exact(conn,n):
    buf=b''
    while len(buf)<n:
        part=conn.recv(n-len(buf))
        if not part:raise AcquisitionError('socket closed early')
        buf+=part
    return buf

def decode_response(head,payload,transaction):
    if len(head)!=7:raise AcquisitionError('header size')
    tid,protocol,length,unit=struct.unpack('>HHHB',head)
    if (tid,protocol,length,unit)!=(transaction,0,71,UNIT):raise AcquisitionError('unexpected MBAP header')
    if len(payload)!=70 or payload[0]!=4 or payload[1]!=68:raise AcquisitionError('invalid FC04 payload')
    soc=struct.unpack('>H',payload[20:22])[0]/10.0
    if not 0<=soc<=100:raise AcquisitionError('SOC range')
    return soc

def read_soc(host=HOST,port=PORT,timeout=2.0,connector=socket.create_connection):
    if not 0<timeout<=5:raise AcquisitionError('timeout range')
    conn=connector((host,port),timeout)
    try:
        conn.settimeout(timeout)
        tid=1
        request=struct.pack('>HHHBBHH',tid,0,6,UNIT,4,ADDRESS,COUNT)
        conn.sendall(request)
        head=recv_exact(conn,7)
        tid_rx,protocol,length,unit=struct.unpack('>HHHB',head)
        if tid_rx!=tid or protocol!=0 or unit!=UNIT or length!=71:raise AcquisitionError('invalid MBAP response')
        return decode_response(head,recv_exact(conn,length-1),tid)
    finally:conn.close()

def append(path,obj):
    path=pathlib.Path(path)
    if path.is_symlink() or path.parent.is_symlink() or not path.parent.is_dir():raise AcquisitionError('unsafe output path')
    fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise AcquisitionError('output not regular file')
        data=(json.dumps(obj,sort_keys=True,allow_nan=False)+'\n').encode()
        if os.write(fd,data)!=len(data):raise AcquisitionError('short journal write')
        os.fsync(fd)
    finally:os.close(fd)

def run(duration,interval,path,reader=read_soc,clock=time.monotonic,sleeper=time.sleep):
    if not 1<=duration<=1800 or not 1<=interval<=10:raise AcquisitionError('bounded range')
    start=clock();deadline=start+duration;count=0;failures=0;last=None
    while clock()<deadline:
        observed=dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            soc=reader();valid=True;error=None
        except (OSError,ValueError,RuntimeError,socket.timeout) as exc:
            soc=None;valid=False;error=type(exc).__name__;failures+=1
        row={'schema':'SIGEN_PHASE3B_RC8_SOC_ONLY','timestamp_utc':observed,'soc_pct':soc,'valid':valid,
             'error':error,'battery_kw':None,'grid_kw':None,'energy_boundary':'SOC_ONLY_NO_POWER_EVIDENCE',
             'grid_side_delivery_verified':False,'modbus_writes':0}
        append(path,row);count+=1
        if last is not None and clock()<last:raise AcquisitionError('monotonic clock regression')
        last=clock()
        remaining=deadline-clock()
        if remaining<=0:break
        sleeper(min(interval,remaining))
    return {'status':'COMPLETED_SOC_ONLY','actual_samples':count,'failed_reads':failures,
            'power_direction_verified':False,'grid_side_delivery_verified':False,'modbus_writes':0}

def main(argv=None):
    p=argparse.ArgumentParser(description='Read-only bounded SOC samples; no power or energy claims')
    p.add_argument('--seconds',type=int,default=30);p.add_argument('--interval-seconds',type=float,default=2)
    p.add_argument('--out',type=pathlib.Path,default=pathlib.Path('/opt/sigenstor/data/rtm/phase3b-rc8-soc-only.jsonl'))
    p.add_argument('--execute-slot',action='store_true')
    args=p.parse_args(argv)
    if args.execute_slot:
        print('BLOCKED: SOC acquisition cannot actuate; MODBUS_WRITES=0');return 2
    try:
        result=run(args.seconds,args.interval_seconds,args.out)
        print(json.dumps(result,sort_keys=True));return 0 if result['failed_reads']==0 else 2
    except (OSError,ValueError,TypeError) as exc:
        print('PHASE3B_RC8_FAIL_CLOSED',type(exc).__name__,str(exc),'MODBUS_WRITES=0');return 2
if __name__=='__main__':sys.exit(main())
