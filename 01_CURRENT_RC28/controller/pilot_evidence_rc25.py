#!/usr/bin/env python3
"""Offline/read-only evidence classification for attended-pilot audit events.

No inverter transport, no Modbus writes. Audit events alone cannot show physical
battery energy transfer. Actual delivered power needs separately observed,
time-aligned grid/battery measurements and commissioning review.
"""
import argparse
import json
from pathlib import Path

SCHEMA='SIGEN_PHASE3B_RC25_PILOT_AUDIT_REVIEW'
class EvidenceHold(ValueError): pass

def assess(events):
    if not isinstance(events,list): raise EvidenceHold('events list required')
    names=[]; session=None; sample_count=0; aborted=False
    for item in events:
        if not isinstance(item,dict) or set(item)!={'event','detail'}:raise EvidenceHold('invalid event envelope')
        name=item['event']; detail=item['detail']
        if not isinstance(name,str) or not isinstance(detail,dict):raise EvidenceHold('invalid event')
        sid=detail.get('session_id')
        if type(sid) is not str or not sid:raise EvidenceHold('session missing')
        if session is None:session=sid
        if session!=sid:raise EvidenceHold('mixed session evidence')
        names.append(name)
        if name=='PILOT_SAMPLE':
            import math
            if any(type(detail.get(k)) not in (int,float) or not math.isfinite(detail[k]) for k in ('soc_pct','battery_kw','grid_kw')):raise EvidenceHold('invalid sample')
            if not 0<=detail['soc_pct']<=100:raise EvidenceHold('invalid SOC')
            sample_count+=1
        if name=='PILOT_ABORT':aborted=True
    started='PILOT_START_ATTEMPT' in names
    handed='PILOT_HANDBACK_VERIFIED' in names
    panel='PILOT_PANEL_RESTORED' in names
    arm='PILOT_LATCH_ARMED' in names
    correct_order=False
    if arm and started and handed and panel:
        correct_order=names.index('PILOT_LATCH_ARMED')<names.index('PILOT_START_ATTEMPT')<names.index('PILOT_HANDBACK_VERIFIED')<names.index('PILOT_PANEL_RESTORED')
    complete=correct_order and sample_count>=2 and not aborted and not any(x.startswith('PILOT_CRITICAL') for x in names)
    return {'schema':SCHEMA,'session_id':session,'status':'AUDIT_SEQUENCE_COMPLETE' if complete else 'HOLD_INCOMPLETE_OR_ABORTED',
            'sample_events':sample_count,'handback_event_recorded':handed,'panel_restoration_event_recorded':panel,
            'grid_side_battery_delivery_verified':False,'host_loss_recovery_verified':False,
            'autonomous_dispatch':False,'modbus_writes_issued_by_assessor':0}

def main(argv=None):
    parser=argparse.ArgumentParser(description='Offline review of JSONL audit envelope; never actuates')
    parser.add_argument('--audit-jsonl',type=Path)
    args=parser.parse_args(argv)
    if args.audit_jsonl is None:
        print('RC25_READONLY_AUDIT_ASSESSOR: NO LIVE CLI; MODBUS_WRITES=0');return 0
    try:
        if args.audit_jsonl.stat().st_size>2_000_000:raise EvidenceHold('audit too large')
        with args.audit_jsonl.open('r',encoding='utf-8') as f:events=[json.loads(row) for row in f if row.strip()]
        out=assess(events);print(json.dumps(out,sort_keys=True));return 0 if out['status']=='AUDIT_SEQUENCE_COMPLETE' else 2
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print('RC25_HOLD',type(exc).__name__,str(exc),'MODBUS_WRITES=0');return 2
if __name__=='__main__':raise SystemExit(main())
