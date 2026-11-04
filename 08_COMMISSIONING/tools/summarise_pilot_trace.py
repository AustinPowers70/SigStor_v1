#!/usr/bin/env python3
"""Read-only RC27/RC28 pilot trace summariser. No Modbus, no network, no writes.

Usage: python3 -B summarise_pilot_trace.py /opt/sigenstor/data/rtm/rc27-pilot-<session>.jsonl

Prints per-phase statistics (valid samples only), invalid samples, the session
lifecycle, and for EXPORT, which register-semantics hypothesis the data favours.
Conventions: battery +charge/-discharge; grid +import/-export.
This is correlation evidence only, NOT battery-attributable grid-side metering.
"""

import json,statistics as st,sys

def main(path):
    rows=[json.loads(l) for l in open(path) if l.strip()]
    ev=[r for r in rows if r.get('record_type')=='SESSION_EVENT']
    sm=[r for r in rows if r.get('record_type')=='PLANT_SAMPLE']
    res=next((e for e in ev if e.get('event')=='SESSION_RESULT'),{})
    print('session',res.get('session_id'),'action',res.get('action'),'status',res.get('status'))
    print('lifecycle',[e.get('event') for e in ev])
    print('exit',res.get('live_controller_exit'),'handback',res.get('plant_handback_verified'),'panel',res.get('panel_restored'))
    out={}
    print(f"{'phase':7}{'n':>3} {'batt_kW mean [min..max]':>28} {'grid_kW mean [min..max]':>28} {'home_kW mean':>13} {'SOC':>6}")
    for ph in ('BEFORE','DURING','AFTER'):
        v=[r for r in sm if r.get('phase')==ph and r.get('valid') is True]
        if not v:print(ph,'no valid samples');continue
        b=[r['battery_kw'] for r in v];g=[r['grid_kw'] for r in v];h=[r['home_kw'] for r in v]
        out[ph]=(st.mean(b),st.mean(g),st.mean(h))
        print(f"{ph:7}{len(v):>3} {st.mean(b):>8.3f} [{min(b):.3f}..{max(b):.3f}]{'':4} {st.mean(g):>8.3f} [{min(g):.3f}..{max(g):.3f}]{'':4} {st.mean(h):>8.3f} {v[-1]['soc_pct']:>6.1f}")
    bad=[r for r in sm if r.get('valid') is not True]
    for r in bad:print('INVALID',r.get('phase'),r.get('timestamp_utc'),r.get('error'))
    if res.get('action')=='EXPORT' and 'DURING' in out:
        b,g,h=out['DURING']
        print('\nEXPORT register-semantics check (DURING means):')
        print(f"  H1 inverter/PCS output = 650 W  -> expect battery ~ -0.65 kW (+/-0.15):  battery {b:+.3f}  {'CONSISTENT' if abs(b+0.65)<=0.15 else 'not consistent'}")
        print(f"  H2 grid connection point = 650 W export -> expect grid ~ -0.65 kW (+/-0.15): grid {g:+.3f}  {'CONSISTENT' if abs(g+0.65)<=0.15 else 'not consistent'}")
        if b>0.05:print('  WARNING: battery CHARGING during EXPORT command -> 40001 sign must be re-examined before any further export use')
        if b<-1.5 and g>-0.3:print('  NOTE: large discharge without export: check for house-load change')
    print('\nCorrelation only; physical_delivery_verified remains False.')
if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit(__doc__)
    main(sys.argv[1])
