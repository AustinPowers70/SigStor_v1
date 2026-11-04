#!/usr/bin/env python3
"""Phase 3B pre-commissioning safety gate. READ-ONLY; no Modbus writes.

A successful result means that submitted evidence supports *review*, not physical
commissioning or permission to dispatch. In particular grid power is aggregate.
"""
import argparse, datetime as dt, json, math, sys
from pathlib import Path

MAX_SAMPLE_GAP_SECONDS = 6.0
MIN_SAMPLE_COUNT = 5
ALLOWED_ACTIONS = {'EXPORT','GRID_CHARGE'}
MAX_RATED_KW = {'EXPORT':0.650,'GRID_CHARGE':0.500}

def _stamp(value):
    if not isinstance(value,str): raise ValueError('timestamp must be string')
    x=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if x.tzinfo is None: raise ValueError('timezone required')
    return x.astimezone(dt.timezone.utc)

def evaluate(plan, samples, events):
    """Deterministic evidence-only gate. Never interprets synthetic data as physical proof."""
    problems=[]
    if not isinstance(plan,dict) or not isinstance(samples,list) or not isinstance(events,list):
        raise ValueError('invalid input types')
    action=plan.get('action')
    if action not in ALLOWED_ACTIONS: problems.append('INVALID_ACTION')
    if plan.get('autonomous_dispatch') is not False: problems.append('AUTONOMOUS_DISPATCH_NOT_DISABLED')
    if plan.get('operator_approved') is not True: problems.append('MANUAL_APPROVAL_ABSENT')
    if plan.get('single_writer_verified') is not True: problems.append('SINGLE_WRITER_NOT_VERIFIED')
    if plan.get('authority_isolated') is not True: problems.append('AUTHORITY_NOT_ISOLATED')
    if plan.get('rc13_unchanged') is not True: problems.append('RC13_CHANGE_NOT_EXCLUDED')
    if plan.get('discharge_limit_untouched') is not True: problems.append('REGISTER_40034_NOT_PROTECTED')
    if plan.get('slot_qualification_continuous') is not True: problems.append('QUALIFICATION_NOT_CONTINUOUS')
    if plan.get('remote_ems_verified_off_before') is not True: problems.append('REMOTE_EMS_PRECONDITION_UNVERIFIED')
    if plan.get('handback_remote_ems_off') is not True: problems.append('HANDBACK_REMOTE_EMS_UNVERIFIED')
    if plan.get('handback_self_consumption') is not True: problems.append('HANDBACK_SELF_CONSUMPTION_UNVERIFIED')
    if action=='EXPORT' and plan.get('handback_pcs_zero') is not True: problems.append('PCS_REQUEST_NOT_VERIFIED_ZERO')
    if plan.get('operator_attended') is not True: problems.append('OPERATOR_ATTENDANCE_UNVERIFIED')
    if plan.get('independent_recovery_qualified') is not True:
        # Informational for supervised operations, but disallows any claim of autonomous release.
        pass
    if action in MAX_RATED_KW:
        try:
            p=float(plan['rated_kw'])
            if not math.isfinite(p) or p<=0 or p>MAX_RATED_KW[action]+1e-9: problems.append('POWER_LIMIT_EXCEEDED')
        except (KeyError,TypeError,ValueError): problems.append('INVALID_POWER')
    try:
        begin=_stamp(plan['start_utc']); end=_stamp(plan['end_utc'])
        if not 0<(end-begin).total_seconds()<=1800: problems.append('INVALID_SLOT_DURATION')
    except (KeyError,ValueError,TypeError):
        begin=end=None;problems.append('INVALID_SLOT_TIMING')
    clean=[]
    for row in samples:
        try:
            if not isinstance(row,dict) or row.get('valid') is not True: raise ValueError()
            t=_stamp(row['observed_utc'])
            soc=float(row['soc_pct']); battery=float(row['battery_kw']); grid=float(row['grid_kw'])
            if not all(math.isfinite(z) for z in (soc,battery,grid)) or not 0<=soc<=100: raise ValueError()
            if begin is not None and not begin<=t<=end: raise ValueError()
            clean.append((t,soc,battery,grid))
        except (ValueError,TypeError,KeyError):problems.append('INVALID_IN_SESSION_SAMPLE')
    clean.sort(key=lambda x:x[0])
    if len(clean)<MIN_SAMPLE_COUNT:problems.append('INSUFFICIENT_ACTUAL_SAMPLES')
    gaps=[(b[0]-a[0]).total_seconds() for a,b in zip(clean,clean[1:])]
    if any(g<=0 or g>MAX_SAMPLE_GAP_SECONDS for g in gaps): problems.append('DUPLICATE_OR_GAPPED_SAMPLES')
    if clean and begin is not None and ((clean[0][0]-begin).total_seconds()>MAX_SAMPLE_GAP_SECONDS or (end-clean[-1][0]).total_seconds()>MAX_SAMPLE_GAP_SECONDS):
        problems.append('BOUNDARY_COVERAGE_UNVERIFIED')
    if action=='GRID_CHARGE' and any(soc>=95 for _,soc,_,_ in clean): problems.append('SOC_CEILING_VIOLATED')
    if action=='EXPORT':
        try:
            reserve=float(plan['soft_reserve_pct'])
            if not math.isfinite(reserve) or any(soc<reserve+2 for _,soc,_,_ in clean): problems.append('RESERVE_VIOLATED')
        except (KeyError,TypeError,ValueError): problems.append('RESERVE_UNKNOWN')
    event_names=[e.get('event') for e in events if isinstance(e,dict)]
    if 'START_ATTEMPTED' not in event_names: problems.append('START_EVIDENCE_MISSING')
    if 'HANDBACK_VERIFIED' not in event_names: problems.append('HANDBACK_EVENT_MISSING')
    if any(x in event_names for x in ('CRITICAL_HANDBACK_UNVERIFIED','CRITICAL_AUTHORITY_RESTART_FAILED')):
        problems.append('CRITICAL_EVENT_PRESENT')
    return {'schema':'SIGEN_PHASE3B_RC13_COMMISSIONING_REVIEW','review_ready':not problems,
            'release_authorised':False,'live_actuation_enabled':False,'modbus_writes':0,
            'grid_side_battery_delivery_verified':False,
            'energy_boundary':'AGGREGATE_GRID_AND_BATTERY_PORT_NOT_INDEPENDENT_ALLOCATION',
            'actual_sample_count':len(clean),'max_actual_gap_seconds':max(gaps,default=None),
            'issues':sorted(set(problems))}

def main(argv=None):
    p=argparse.ArgumentParser(description='Offline evidence review; no plant control')
    p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--execute-slot',action='store_true')
    a=p.parse_args(argv)
    if a.execute_slot:
        print('BLOCKED: RC13 review tool cannot actuate; MODBUS_WRITES=0');return 2
    try:
        if a.evidence.is_symlink() or not a.evidence.is_file():raise ValueError('unsafe evidence path')
        d=json.loads(a.evidence.read_text())
        report=evaluate(d['plan'],d['samples'],d['events'])
        print(json.dumps(report,sort_keys=True,indent=2,allow_nan=False))
        return 0 if report['review_ready'] else 2
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print('RC13_FAIL_CLOSED',type(exc).__name__,str(exc),'MODBUS_WRITES=0');return 2
if __name__=='__main__':sys.exit(main())
