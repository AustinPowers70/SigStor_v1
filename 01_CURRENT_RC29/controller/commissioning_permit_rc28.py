#!/usr/bin/env python3
"""Manual commissioning-only qualification, WITHOUT RC13 economic-slot permission.

This is NOT trading authorisation and cannot run alone. Mandatory plant, reserve,
manual authority and panel checks happen here and again in the commissioned
actuator. No Modbus writes in this module.
"""
import json,math,stat
from pathlib import Path
from commissioning_preflight_rc18 import inspect
from controller import AUTH_UNIT,systemctl
from rc13_gateway import AUTH,SET

class PermitHold(RuntimeError):pass

def safe_json(p):
    p=Path(p)
    if p.is_symlink() or not p.is_file() or not stat.S_ISREG(p.stat().st_mode):
        raise PermitHold('missing/unsafe input: '+str(p))
    return json.loads(p.read_text())

def qualify(action,stage='PRE',*,authority_path=AUTH,reserve_path=SET,preflight=inspect,panel=systemctl):
    if action not in ('GRID_CHARGE','EXPORT'):raise PermitHold('unknown commissioning action')
    authority=safe_json(authority_path); settings=safe_json(reserve_path)
    reserve=settings.get('SoftReservePercent')
    if type(reserve) is not int or reserve not in range(0,96,5):raise PermitHold('invalid soft reserve')
    if (authority.get('requested')!='MANUAL' or authority.get('dispatch_authorised') is not False
         or authority.get('remote_ems_verified_off') is not True):
        raise PermitHold('MANUAL authority not exclusive or not acknowledged')
    if stage not in ('PRE','ISOLATED','ACTIVE'):raise PermitHold('invalid phase')
    if stage=='PRE':
        check=preflight()
        if check.get('plant_handback_verified') is not True:raise PermitHold('physical handback not verified')
        soc=check.get('soc_pct')
        if type(soc) not in (float,int) or not math.isfinite(soc) or not 0<=soc<=100:raise PermitHold('invalid SOC')
        if action=='GRID_CHARGE' and not reserve<=soc<95:raise PermitHold('charge SOC outside bounds')
        if action=='EXPORT' and not reserve+2<=soc<=98:raise PermitHold('export SOC outside bounds')
        service=panel('is-active',AUTH_UNIT)
        if service.returncode or service.stdout.strip()!='active':raise PermitHold('authority panel unhealthy')
    return {'Decision':action,'StartUtc':'MANUAL_COMMISSIONING_30S','AuthorityManualReady':True,
            'CommissioningOnly':True,'DispatchAuthorised':False,'ModbusWrites':0},reserve
