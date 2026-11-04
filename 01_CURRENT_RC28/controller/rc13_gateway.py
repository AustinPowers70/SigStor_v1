#!/usr/bin/env python3
"""RC13 bounded supervisory handoff. Does not import any Modbus library or write to plant."""
import argparse, json, math, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

DOC=Path('/opt/sigenstor/data/rtm/v12-demand-backed-qualified-rc13.json')
SET=Path('/opt/sigenstor/data/SoftReserveSettings.json')
AUTH=Path('/opt/sigenstor/data/control-authority.json')

def timestamp(s):
    d=datetime.fromisoformat(s.replace('Z','+00:00'))
    if d.tzinfo is None: raise ValueError('naive time')
    return d.astimezone(timezone.utc)

def validate(doc, setting, authority, now):
    b,c,r=doc['Bridge'],doc['Candidate'],doc['Reconciliation']
    if doc.get('DispatchEnabled') is not False or doc.get('ResearchOnly') is not True: raise ValueError('unsafe envelope')
    if c.get('Schema')!='SIGENSTOR_RTM_V12_UNIFIED_ADVISORY' or c.get('Status')!='OPTIMAL_RESEARCH_CANDIDATE' or c.get('SolverStatus')!=0: raise ValueError('solver unqualified')
    if c.get('ResearchOnly') is not True or any(c.get(k) is not False for k in ('DispatchEnabled','TradingApproved','ProductionApproved')): raise ValueError('unsafe candidate')
    if r.get('Qualification')!='INDEPENDENT_MODEL_RECONCILED_ADVISORY_ONLY' or r.get('LiveDispatchQualification')!='NOT_APPROVED' or r.get('OperatorExecutionAllowed') is not False: raise ValueError('not independently qualified')
    if r.get('ModbusCommandsIssued')!=0 or r.get('DispatchEnabled') is not False: raise ValueError('unsafe reconciliation')
    if r.get('SourceSnapshotUtc')!=c.get('SourceSnapshotUtc'): raise ValueError('source mismatch')
    age=(now-timestamp(c['SourceSnapshotUtc'])).total_seconds()
    if age < -120 or age>600: raise ValueError('stale source')
    if not isinstance(setting.get('SoftReservePercent'),int) or isinstance(setting['SoftReservePercent'],bool) or setting['SoftReservePercent'] not in range(0,96,5):raise ValueError('reserve setting invalid')
    reserve=setting['SoftReservePercent']
    if float(c.get('SoftReservePercent',-1))!=reserve or float(r.get('SoftReservePercent',-1))!=reserve:raise ValueError('reserve mismatch')
    if abs(float(b['TerminalDemandCommitmentKwh'])-float(c['RequiredTerminalKwh']))>0.001:raise ValueError('terminal commitment mismatch')
    rows=c['Schedule']
    if len(rows)!=c.get('ForecastSlots') or len(rows)!=r.get('ForecastSlots') or not rows:raise ValueError('incomplete schedule')
    active=[]
    for row in rows:
        start=timestamp(row['StartUtc']); end=start+timedelta(minutes=30)
        if start<=now<end:active.append(row)
    if len(active)>1:raise ValueError('overlapping actions')
    authority_ok=(authority.get('requested')=='MANUAL' and authority.get('dispatch_authorised') is False and authority.get('remote_ems_verified_off') is True)
    if not active: return {'Decision':'HOLD_OUTSIDE_HORIZON','AuthorityManualReady':authority_ok,'ModbusWrites':0}
    row=active[0]; charge=float(row['GridChargeKwh']); export=float(row['GridExportKwh'])
    if not all(math.isfinite(x) and x>=0 for x in (charge,export)): raise ValueError('invalid energy')
    if charge>.001 and export>.001:raise ValueError('conflicting action')
    if charge<=.01 and export<=.01: kind='HOLD'
    else:kind='EXPORT' if export>.01 else 'GRID_CHARGE'
    return {'Decision':kind if authority_ok else 'HOLD_AUTHORITY_NOT_READY','ProposedAction':kind,'StartUtc':row['StartUtc'],'ScheduledEnergyKwh':round(max(charge,export),5),'AuthorityManualReady':authority_ok,'DispatchAuthorised':False,'ModbusWrites':0}

def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,default=DOC);p.add_argument('--settings',type=Path,default=SET);p.add_argument('--authority',type=Path,default=AUTH);a=p.parse_args()
    try:
        for path in (a.candidate,a.settings,a.authority):
            if path.is_symlink() or not path.is_file():raise ValueError('missing or symlink '+str(path))
        out=validate(*[json.loads(p.read_text()) for p in (a.candidate,a.settings,a.authority)],datetime.now(timezone.utc))
        print('RC13_SUPERVISORY_GATEWAY',json.dumps(out,sort_keys=True))
        print('RESEARCH_ONLY EXECUTION_DISABLED MODBUS_WRITES=NONE')
    except Exception as e:
        print('RC13_SUPERVISORY_GATEWAY HOLD_BLOCKED',str(e),'MODBUS_WRITES=NONE');return 2
    return 0
if __name__=='__main__':sys.exit(main())
