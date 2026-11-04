#!/usr/bin/env python3
"""Read-only aggregation of Phase 2 operational evidence, without plant/network access."""
import datetime as dt
import json
import os
import tempfile
from pathlib import Path

ROOT = Path('/opt/sigenstor/data/rtm')
OUT = ROOT / 'phase2-dashboard-r9.json'
SOURCES = {
    'r5': ('phase2-operational-status.json', 'SIGEN_PHASE2_OPERATIONAL_R5'),
    'r6': ('phase2-operational-r6.json', 'SIGEN_PHASE2_OPERATIONAL_R6'),
    'r7': ('phase2-operational-r7.json', 'SIGEN_PHASE2_OPERATIONAL_R7'),
    'r8': ('phase2-session-r8.json', 'SIGEN_PHASE2_SESSION_R8'),
}
UTC = dt.timezone.utc


def aggregate(root, now):
    reasons = []
    components = {}
    for key, (file, schema) in SOURCES.items():
        try:
            path = root / file
            if path.is_symlink():
                raise ValueError('symlink source')
            doc = json.loads(path.read_text())
            if doc.get('schema') != schema:
                raise ValueError('schema mismatch')
            stamp = dt.datetime.fromisoformat(doc['timestamp_utc'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('naive timestamp')
            age = (now - stamp.astimezone(UTC)).total_seconds()
            if not -30 <= age <= 180:
                raise ValueError('stale/future timestamp')
            if key in ('r6', 'r7', 'r8') and doc.get('dispatch_enabled') is not False:
                raise ValueError('unsafe dispatch state')
            if doc.get('plant_writes') != 0:
                raise ValueError('unexpected plant writes')
            components[key] = {'healthy': True, 'age_seconds': round(max(0, age), 2),
                               'state': doc.get('state') or doc.get('reason') or 'UNKNOWN'}
            if key == 'r6' and doc.get('reasons'):
                reasons.append('R6_ALERT')
            if key == 'r7' and doc.get('state') != 'PASSIVE_HEALTHY':
                reasons.append('R7_FAULT')
            if key == 'r8' and (doc.get('state') == 'ATTENTION_REQUIRED' or doc.get('reasons')):
                reasons.append('R8_SESSION_ATTENTION')
            if key == 'r5':
                components[key]['decision'] = doc.get('r4_decision')
                components[key]['eligible'] = doc.get('r4_eligible') is True
            if key == 'r8':
                components[key]['last_verified_handback'] = doc.get('last_verified_handback')
                components[key]['unresolved_operation'] = doc.get('unresolved_operation')
        except (OSError, ValueError, TypeError, KeyError) as exc:
            reasons.append(key.upper() + '_UNAVAILABLE_OR_INVALID')
            components[key] = {'healthy': False, 'error': type(exc).__name__}
    return {'schema': 'SIGEN_PHASE2_DASHBOARD_R9', 'timestamp_utc': now.isoformat(),
            'state': 'ATTENTION_REQUIRED' if reasons else 'PASSIVE_HEALTHY',
            'reasons': sorted(set(reasons)), 'components': components,
            'economic_model': 'RC13_FROZEN', 'control_mode': 'SUPERVISED_ONLY',
            'dispatch_enabled': False, 'plant_writes': 0,
            'recovery': 'ALERT_ONLY_NO_PLANT_RECOVERY'}


def atomic_write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.r9-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(doc, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    result = aggregate(ROOT, dt.datetime.now(UTC))
    atomic_write(OUT, result)
    print(json.dumps(result, sort_keys=True))
    print('PHASE2_R9_DASHBOARD_FEED_' + result['state'] + '_NO_MODBUS_WRITES')
    return 0 if result['state'] == 'PASSIVE_HEALTHY' else 2

if __name__ == '__main__':
    raise SystemExit(main())
