#!/usr/bin/env python3
"""Slot commitment accounting: no plant I/O; conservative planning for supervised use.

Full-slot scheduled grid-side energy is a commitment across the entire interval,
not a fresh request for that same amount at every second within the interval.
Until actual delivered grid-side energy is independently metered, no live
continuation against an outstanding commitment can be authorised.
"""
import datetime as dt
import math
import rc13_gateway as gateway

class CommitmentError(ValueError): pass

MAX_DURATION_S=1800
RATED_KW={'GRID_CHARGE':0.5,'EXPORT':0.65}

def calculate(*,action,start_utc,scheduled_kwh,now,delivered_grid_kwh=None):
    if action not in RATED_KW:raise CommitmentError('unsupported action')
    start=gateway.timestamp(start_utc)
    if now.tzinfo is None:raise CommitmentError('naive current time')
    now=now.astimezone(dt.timezone.utc)
    end=start+dt.timedelta(seconds=MAX_DURATION_S)
    if not start<=now<end:raise CommitmentError('outside qualified slot')
    try: target=float(scheduled_kwh)
    except (ValueError,TypeError):raise CommitmentError('invalid scheduled kWh')
    if not math.isfinite(target) or target<=0:raise CommitmentError('invalid scheduled kWh')
    power=RATED_KW[action]
    slot_capacity=power*MAX_DURATION_S/3600
    if target>slot_capacity+1e-6:raise CommitmentError('commitment exceeds commissioned full-slot capacity')
    elapsed=(now-start).total_seconds();remaining=(end-now).total_seconds()
    remaining_capacity=power*remaining/3600
    out={'action':action,'slot_start_utc':start.isoformat(),'slot_end_utc':end.isoformat(),
         'scheduled_grid_side_kwh':target,'commissioned_kw':power,
         'remaining_seconds':remaining,'remaining_max_kwh':remaining_capacity,
         'grid_side_evidence_verified':False,'live_dispatch_allowed':False}
    if delivered_grid_kwh is None:
        out.update({'state':'HOLD_UNMETERED_DELIVERY','outstanding_grid_side_kwh':None,
                    'reason':'no independent delivered grid-side energy evidence'})
        return out
    try:delivered=float(delivered_grid_kwh)
    except (TypeError,ValueError):raise CommitmentError('invalid delivered grid-side kWh')
    if not math.isfinite(delivered) or delivered<0:raise CommitmentError('invalid delivered grid-side kWh')
    outstanding=max(0.0,target-delivered)
    out.update({'outstanding_grid_side_kwh':outstanding,'remaining_feasible':outstanding<=remaining_capacity+1e-6,
                'state':'READ_ONLY_REMAINING_COMMITMENT_ESTIMATE',
                'reason':'meter value not independently qualified for controller actuation'})
    return out
