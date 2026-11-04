#!/usr/bin/env python3
"""Read-only, explicitly operator-run commissioning preflight. No plant writes."""
import argparse, json, struct, datetime
from supervised_charge import Modbus
from power_acquisition_rc9 import sample_once

class PreflightHold(RuntimeError): pass

def inspect(connect=None, sample=None):
    connect=connect or (lambda:Modbus('192.168.0.8',timeout=3))
    sample=sample or sample_once
    con=connect()
    try:
        remote=con.read_holding(40029)
        mode=con.read_holding(40031)
        words=con.call(3,struct.pack('>HH',40001,2))
        pcs_zero=(words==b'\x04\x00\x00\x00\x00')
    finally:
        con.close()
    power=sample()
    soc=float(power['soc_pct'])
    if not 0<=soc<=100:raise PreflightHold('SOC invalid')
    result={'schema':'SIGEN_PHASE3B_RC18_LIVE_READONLY_PREFLIGHT',
            'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'remote_ems_off':remote==0,'self_consumption':mode==2,
            'pcs_zero':pcs_zero,'soc_pct':soc,
            'battery_kw':float(power['battery_kw']), 'grid_kw':float(power['grid_kw']),
            'plant_handback_verified':remote==0 and mode==2 and pcs_zero,
            'execution_enabled':False,'modbus_writes':0,
            'grid_side_battery_delivery_verified':False}
    result['status']='READY_FOR_OPERATOR_REVIEW' if result['plant_handback_verified'] else 'HOLD_PLANT_NOT_HANDED_BACK'
    return result

def main():
    parser=argparse.ArgumentParser(description='Read-only real plant commissioning preflight')
    parser.add_argument('--check',action='store_true',help='connect and perform read-only FC03/FC04 checks')
    args=parser.parse_args()
    if not args.check:
        print('RC18_STAGED: pass --check for read-only Modbus inspection; MODBUS_WRITES=0');return 0
    try:
        result=inspect();print(json.dumps(result,sort_keys=True,allow_nan=False));return 0 if result['plant_handback_verified'] else 2
    except Exception as e:
        print('RC18_FAIL_CLOSED',type(e).__name__,str(e),'MODBUS_WRITES=0');return 2
if __name__=='__main__':raise SystemExit(main())
