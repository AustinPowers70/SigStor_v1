#!/usr/bin/env python3
"""Operator-only PCS export pulse on previously commissioned registers.
NO autonomous scheduling; never write register 40034.
"""
import fcntl, time
from supervised_charge import Modbus

def export_handback(host, plant_cls=Modbus, sleep=time.sleep):
    """Best effort: neutralise PCS request, restore self-consumption, disable Remote EMS."""
    for attempt in range(3):
        con = None
        try:
            con = plant_cls(host)
            # Reset PCS request first; continue to disable even if it fails.
            errors=[]
            for fn in (lambda: con.write_u32(40001,0),
                       lambda: con.write(40031,2),
                       lambda: con.write(40029,0)):
                try: fn()
                except Exception as e: errors.append(str(e))
            off=con.read_holding(40029)==0
            self_consumption=con.read_holding(40031)==2
            # Zero PCS demand must be checked as two consecutive 16-bit words.
            response=con.call(3,__import__('struct').pack('>HH',40001,2))
            pcs_zero=(len(response)==5 and response[0]==4 and response[1:]==bytes(4))
            if off and self_consumption and pcs_zero and not errors: return True
        except Exception:
            pass
        finally:
            if con is not None: con.close()
        sleep(1)
    return False

def perform_export(*,qualify,systemctl,audit,lock,auth_unit,host,plant_cls=Modbus,
                   handback=export_handback, sleep=time.sleep,clock=time.monotonic,qualification=None):
    """Explicit 650 W / 30s pilot; strict fresh RC13 export and MANUAL authority gating."""
    eligibility = qualification or (lambda stage: qualify_export(qualify))
    with lock.open('a+b') as fp:
        fcntl.flock(fp,fcntl.LOCK_EX | fcntl.LOCK_NB)
        action,reserve=eligibility("PRE")
        check=systemctl('is-active',auth_unit)
        if check.returncode or check.stdout.strip()!='active':
            raise RuntimeError('authority panel not active; no writes')
        stopped=systemctl('stop',auth_unit)
        if stopped.returncode:raise RuntimeError('could not isolate authority panel; no writes')
        entered=False
        handback_ok=True
        try:
            if systemctl('is-active',auth_unit).stdout.strip()=='active':
                raise RuntimeError('authority panel isolation unverified')
            newer,newreserve=eligibility("ISOLATED")
            if newer['StartUtc']!=action['StartUtc'] or newreserve!=reserve:
                raise RuntimeError('forecast changed prior to export')
            con=plant_cls(host)
            try:
                soc=con.soc()
                if con.read_holding(40029)!=0:raise RuntimeError('Remote EMS currently in use')
                if not reserve+2<=soc<=98:raise RuntimeError('SOC outside commissioning reserve margins')
                # No writes until both source and live plant preconditions rechecked.
                latest,current=eligibility("ISOLATED")
                if latest['StartUtc']!=action['StartUtc'] or current!=reserve:
                    raise RuntimeError('source changed before export')
                entered=True  # a timeout on the first write may be an ambiguous plant actuation
                con.write(40029,1)
                con.write(40031,0)
                con.write_u32(40001,650)
                if con.read_holding(40029)!=1:raise RuntimeError('Remote EMS not enabled after PCS request')
                audit('EXPORT_PILOT_STARTED','650W/30s '+action['StartUtc'])
                deadline=clock()+30
                while clock()<deadline:
                    sleep(min(2,max(0,deadline-clock())))
                    if con.soc()<reserve+2:raise RuntimeError('SOC approaches reserve margin')
                    current_action,current_reserve=eligibility("ACTIVE")
                    if current_action['StartUtc']!=action['StartUtc'] or current_reserve!=reserve:
                        raise RuntimeError('RC13 window or reserve changed')
                audit('EXPORT_PILOT_ELAPSED','30s')
            finally:con.close()
        finally:
            if entered:
                try:
                    handback_ok=(handback(host) is True)
                except BaseException as exc:
                    handback_ok=False
                    try: audit('CRITICAL_EXPORT_HANDBACK_EXCEPTION',repr(exc))
                    except BaseException: pass
                try: audit('EXPORT_HANDBACK_VERIFIED' if handback_ok else 'CRITICAL_EXPORT_HANDBACK_UNVERIFIED')
                except BaseException:
                    handback_ok=False  # cannot demonstrate auditable successful handback
            if not handback_ok:
                audit('CRITICAL_AUTHORITY_RESTART_WITHHELD',
                      'PCS handback unverified; manual plant recovery required')
                raise RuntimeError('CRITICAL: PCS handback unverified; authority panel remains isolated; check MySigen immediately')
            restart=systemctl('start',auth_unit)
            if restart.returncode:audit('CRITICAL_AUTHORITY_RESTART_FAILED',restart.stderr)
            if restart.returncode:raise RuntimeError('CRITICAL: authority panel restart failed')
    return True

def qualify_export(qualify):
    # Reuse original independently reconciled RC13 source, but select EXPORT not GRID_CHARGE.
    import rc13_gateway as gateway
    import json
    from datetime import datetime,timezone
    paths=(gateway.DOC,gateway.SET,gateway.AUTH)
    for p in paths:
        if p.is_symlink() or not p.is_file():raise RuntimeError('required source unavailable: '+str(p))
    doc,settings,authority=(json.loads(p.read_text()) for p in paths)
    result=gateway.validate(doc,settings,authority,datetime.now(timezone.utc))
    if result.get('Decision')!='EXPORT' or result.get('AuthorityManualReady') is not True:
        raise RuntimeError('no qualified RC13 EXPORT window and exclusive MANUAL authority: '+str(result.get('Decision')))
    if result.get('ScheduledEnergyKwh',0)<0.025:
        raise RuntimeError('export interval energy below pilot minimum')
    return result,settings['SoftReservePercent']
