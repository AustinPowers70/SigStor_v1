#!/usr/bin/env python3
"""Operator-initiated commissioning only. Never a scheduled dispatch service."""
import argparse,fcntl,json,os,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
import rc13_gateway as gateway
from supervised_charge import Modbus,handback
from supervised_export import perform_export

LOCK=Path('/run/lock/sigen-rtm-v12-commission.lock')
AUTH_UNIT='sigen-rtm-authority-panel.service'
HOST='192.168.0.8'
AUDIT=Path('/opt/sigenstor/data/rtm/phase1-supervised-audit.jsonl')

def qualify():
    inputs=[]
    for p in (gateway.DOC,gateway.SET,gateway.AUTH):
        if p.is_symlink() or not p.is_file():raise RuntimeError('required source unavailable/unsafe: '+str(p))
        inputs.append(json.loads(p.read_text()))
    out=gateway.validate(*inputs,datetime.now(timezone.utc))
    if out.get('Decision')!='GRID_CHARGE' or out.get('AuthorityManualReady') is not True:
        raise RuntimeError('no currently qualified charge window under MANUAL authority: '+str(out.get('Decision')))
    if out.get('ScheduledEnergyKwh',0)<0.025:raise RuntimeError('charge interval below commissioning minimum')
    return out,inputs[1]['SoftReservePercent']

def systemctl(*args):
    return subprocess.run(['systemctl',*args],capture_output=True,text=True,timeout=20)

def audit(event,detail=''):
    AUDIT.parent.mkdir(parents=True,exist_ok=True)
    with AUDIT.open('a') as f:
        f.write(json.dumps({'timestamp':datetime.now(timezone.utc).isoformat(),'event':event,'detail':str(detail)})+'\n')
        f.flush();os.fsync(f.fileno())

def execute(seconds=30,sleep=time.sleep,clock=time.monotonic,plant_cls=Modbus,release=handback,qualification=None):
    qualification = qualification or (lambda stage: qualify())
    if seconds != 30:raise RuntimeError('only fixed 30-second bounded pulse supported')
    LOCK.parent.mkdir(parents=True,exist_ok=True)
    with LOCK.open('a+b') as fp:
        fcntl.flock(fp,fcntl.LOCK_EX|fcntl.LOCK_NB)
        action,reserve=qualification("PRE")
        # Prevent competing authority changes from the HTTP panel throughout pulse.
        state=systemctl('is-active',AUTH_UNIT)
        if state.returncode!=0 or state.stdout.strip()!='active':raise RuntimeError('authority panel must be healthy before isolation')
        stop=systemctl('stop',AUTH_UNIT)
        if stop.returncode:raise RuntimeError('authority panel isolation failed: '+stop.stderr.strip())
        entered=False
        try:
            if systemctl('is-active',AUTH_UNIT).stdout.strip()=='active':raise RuntimeError('authority panel still active')
            action2,reserve2=qualification("ISOLATED")
            if action2['StartUtc']!=action['StartUtc'] or reserve!=reserve2:raise RuntimeError('schedule changed')
            # A separate operator session must not retain Remote EMS ownership.
            con=plant_cls(HOST)
            try:
                soc=con.soc()
                if con.read_holding(40029)!=0:raise RuntimeError('remote EMS not released')
                if not reserve<=soc<95:raise RuntimeError('SOC outside commissioning bounds')
                qualification("ISOLATED")
                entered=True  # even first write timeout must cause handback attempt
                con.write_u32(40032,500)  # commissioned 0.5 kW limit
                con.write(40031,3)
                con.write(40029,1)
                if con.read_holding(40029)!=1:raise RuntimeError('Remote EMS enable not verified')
                audit('CHARGE_STARTED',action['StartUtc'])
                deadline=clock()+seconds
                while clock()<deadline:
                    sleep(min(2,max(0,deadline-clock())))
                    if con.soc()>=95:raise RuntimeError('SOC high threshold')
                    latest,current_reserve=qualification("ACTIVE")
                    if latest['StartUtc']!=action['StartUtc'] or current_reserve!=reserve:raise RuntimeError('schedule/reserve changed')
                audit('CHARGE_PULSE_ELAPSED','30 seconds maximum')
            finally:
                con.close()
        finally:
            handback_ok=True
            if entered:
                try:
                    handback_ok=(release(HOST) is True)
                except BaseException as exc:
                    handback_ok=False
                    try: audit('CRITICAL_HANDBACK_EXCEPTION',repr(exc))
                    except BaseException: pass
                try: audit('HANDBACK_VERIFIED' if handback_ok else 'CRITICAL_HANDBACK_UNVERIFIED')
                except BaseException:
                    handback_ok=False  # cannot demonstrate auditable successful handback
            if not handback_ok:
                audit('CRITICAL_AUTHORITY_RESTART_WITHHELD','Handback unverified; require local plant recovery')
                raise RuntimeError('CRITICAL: manual/MySigen handback unverified; authority panel remains isolated')
            restart=systemctl('start',AUTH_UNIT)
            if restart.returncode:audit('CRITICAL_AUTHORITY_RESTART_FAILED',restart.stderr)
            if restart.returncode:raise RuntimeError('CRITICAL: authority panel restart failed')
    return True

def main():
    parser=argparse.ArgumentParser(description='RC13 supervised commissioning; never automatic dispatch')
    grp=parser.add_mutually_exclusive_group(required=True)
    grp.add_argument('--status',action='store_true')
    grp.add_argument('--execute-30s-charge',action='store_true')
    grp.add_argument('--execute-30s-export',action='store_true')
    parser.add_argument('--operator-ack',action='store_true')
    args=parser.parse_args()
    try:
        if args.status:
            x,reserve=qualify()
            print('SUPERVISED_CHARGE_ELIGIBLE',x['StartUtc'],'RESERVE',reserve,'MODBUS_WRITES=NONE')
            return 0
        if not args.operator_ack:raise RuntimeError('explicit --operator-ack required')
        if args.execute_30s_export:
            audit('OPERATOR_REQUESTED_EXPORT')
            perform_export(qualify=qualify,systemctl=systemctl,audit=audit,lock=LOCK,auth_unit=AUTH_UNIT,host=HOST)
            print('SUPERVISED_EXPORT_COMPLETED_HANDBACK_VERIFIED')
            return 0
        audit('OPERATOR_REQUESTED_CHARGE')
        print('OPERATOR-APPROVED LIVE 0.5 kW x 30 s; MySigen handback must be available',flush=True)
        execute()
        print('SUPERVISED_CHARGE_COMPLETED_HANDBACK_VERIFIED')
        return 0
    except Exception as exc:
        print('SUPERVISED_COMMISSION_BLOCKED_OR_FAILED:',exc,flush=True)
        return 2
if __name__=='__main__':sys.exit(main())
