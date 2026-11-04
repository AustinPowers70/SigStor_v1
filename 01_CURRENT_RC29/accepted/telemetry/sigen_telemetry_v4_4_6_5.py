#!/usr/bin/env python3
"""SigenStor v4.4.6.5 read-only Modbus telemetry and rolling 7-day demand CSV.

No Modbus write functions, no Octopus API calls, and no inverter controls.
Requires Python 3.10+ standard library only.
"""
import argparse
import csv
import datetime as dt
import json
import logging
import math
import os
import socket
import sqlite3
import struct
import sys
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = '4.4.6.5'
UTC = dt.timezone.utc
UK = ZoneInfo('Europe/London')
DEFAULT_DIR = Path('/opt/sigenstor/data')
# SigenStor validated FC04 register block: 30005 to 30038 (34 registers).
# 30005/6 signed grid W (+ import, - export); 30014 SOC 0.1%;
# 30035/6 unsigned PV W; 30037/8 signed battery W (+ charge, - discharge).
REG_BASE = 30005
COUNT = 34


def utcnow():
    return dt.datetime.now(UTC)


def parse_utc(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(UTC)


def signed32(registers, idx):
    raw = ((registers[idx] & 65535) << 16) | (registers[idx + 1] & 65535)
    return raw - (1 << 32) if raw >= (1 << 31) else raw


def unsigned32(registers, idx):
    return ((registers[idx] & 65535) << 16) | (registers[idx + 1] & 65535)


def receive_exact(sock, wanted):
    buf = bytearray()
    while len(buf) < wanted:
        data = sock.recv(wanted - len(buf))
        if not data:
            raise ConnectionError('Modbus peer closed connection prematurely')
        buf.extend(data)
    return bytes(buf)


def read_plant(host, port, unit, timeout, protocol_address):
    # Only function code 04 is implemented. 0-based addressing for 30005 is 4;
    # some existing implementations use the numeric 30005 directly as the address.
    # Configurable to match the proven existing scheduler's Modbus request.
    txid = os.getpid() & 0xffff
    request_pdu = struct.pack('>BHH', 4, protocol_address, COUNT)
    request = struct.pack('>HHHB', txid, 0, len(request_pdu) + 1, unit) + request_pdu
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(request)
        mbap = receive_exact(sock, 7)
        rxid, proto, length, rxunit = struct.unpack('>HHHB', mbap)
        if rxid != txid or proto != 0 or rxunit != unit or not (2 <= length <= 254):
            raise ValueError('Invalid Modbus MBAP header')
        pdu = receive_exact(sock, length - 1)
    if pdu[0] == 0x84:
        raise ValueError(f'Modbus FC04 exception code: {pdu[1] if len(pdu)>1 else "missing"}')
    if len(pdu) != 2 + COUNT * 2 or pdu[0] != 4 or pdu[1] != COUNT * 2:
        raise ValueError('Unexpected FC04 payload length or function')
    regs = list(struct.unpack('>' + 'H' * COUNT, pdu[2:]))
    # 30014 is register offset 9, not 10.
    return {
        'grid_kw': signed32(regs, 0) / 1000.0,
        'soc_pct': regs[9] / 10.0,
        'pv_kw': unsigned32(regs, 30) / 1000.0,
        'battery_kw': signed32(regs, 32) / 1000.0,
    }


def validate_sample(sample, max_kw):
    reasons = []
    for key in ('grid_kw','battery_kw','pv_kw','soc_pct'):
        if not math.isfinite(sample[key]):
            reasons.append(f'{key}:not_finite')
    for key in ('grid_kw','battery_kw','pv_kw'):
        if abs(sample[key]) > max_kw:
            reasons.append(f'{key}:out_of_range')
    if not 0 <= sample['soc_pct'] <= 100:
        reasons.append('soc_pct:out_of_range')
    if sample['pv_kw'] < -0.001:
        reasons.append('pv_kw:negative')
    # Sign convention: +grid imports, +battery charges, +PV produces.
    sample['home_kw'] = sample['grid_kw'] + sample['pv_kw'] - sample['battery_kw']
    if sample['home_kw'] < -0.25 or sample['home_kw'] > max_kw:
        reasons.append('home_kw:implausible')
    # Slight negative inference can arise from asynchronous register samples and rounding;
    # preserve sample but clamp only a plausible near-zero negative estimate.
    if -0.25 <= sample['home_kw'] < 0:
        sample['home_kw'] = 0.0
    sample['valid'] = int(not reasons)
    sample['issues'] = ','.join(reasons)
    return sample


def open_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute('PRAGMA busy_timeout=5000')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('''CREATE TABLE IF NOT EXISTS telemetry (
        timestamp_utc TEXT PRIMARY KEY, grid_kw REAL, battery_kw REAL,
        pv_kw REAL, soc_pct REAL, home_kw REAL, valid INTEGER NOT NULL,
        issues TEXT NOT NULL)''')
    db.commit()
    return db


def store(db, stamp, sample):
    db.execute('INSERT OR REPLACE INTO telemetry VALUES (?,?,?,?,?,?,?,?)',
       (stamp, sample['grid_kw'],sample['battery_kw'],sample['pv_kw'],
        sample['soc_pct'],sample['home_kw'],sample['valid'],sample['issues']))
    db.commit()


def atomic_csv(path, fields, rows):
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def atomic_json(path, record):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def export(db, folder, now, min_points, min_days):
    cutoff = now - dt.timedelta(days=7)
    query = db.execute('''SELECT timestamp_utc,grid_kw,battery_kw,pv_kw,soc_pct,
        home_kw,valid,issues FROM telemetry WHERE timestamp_utc>=? AND timestamp_utc<=?
        ORDER BY timestamp_utc''', (cutoff.isoformat(),now.isoformat()))
    points = query.fetchall()
    by_bucket = defaultdict(list)
    invalid = 0
    for stamp, grid, bat, pv, soc, home, valid, issues in points:
        t = parse_utc(stamp)
        if valid:
            key = t.replace(minute=30 if t.minute >= 30 else 0, second=0, microsecond=0)
            by_bucket[key].append((t, home, grid, bat, pv, soc))
        else:
            invalid += 1
    rows, detailed = [], []
    # Only full, completed half-hours with sufficient distinct five-minute readings.
    for key, readings in sorted(by_bucket.items()):
        if key + dt.timedelta(minutes=30) > now:
            continue
        distinct = {t.replace(second=0,microsecond=0).minute//5 for t,*_ in readings}
        if len(distinct) < min_points:
            continue
        average = lambda ix: sum(x[ix] for x in readings) / len(readings)
        home = average(1)
        rows.append({'TimestampUtc':key.isoformat(), 'HomeDemandKw':f'{home:.5f}', 'DurationMinutes':30})
        detailed.append({'TimestampUtc':key.isoformat(), 'Readings':len(readings),
          'HomeDemandKw':round(home,5), 'GridKw':round(average(2),5),
          'BatteryKw':round(average(3),5), 'PvKw':round(average(4),5),
          'SocPct':round(average(5),2)})
    atomic_csv(folder/'HouseholdDemand7d.csv',
               ['TimestampUtc','HomeDemandKw','DurationMinutes'],rows)
    atomic_csv(folder/'HouseholdTelemetryIntervals7d.csv',
               ['TimestampUtc','Readings','HomeDemandKw','GridKw','BatteryKw','PvKw','SocPct'],detailed)
    # Determine readiness via calendar-day variety, plus record actual coverage and freshness.
    dates = {parse_utc(r['TimestampUtc']).astimezone(UK).date() for r in rows}
    expected_completed = max(0, int((now.replace(minute=30 if now.minute >= 30 else 0,
                  second=0,microsecond=0) - cutoff).total_seconds() // 1800))
    latest = rows[-1]['TimestampUtc'] if rows else None
    freshness_minutes = ((now-parse_utc(latest)).total_seconds()/60) if latest else None
    span_days = ((parse_utc(rows[-1]['TimestampUtc']) - parse_utc(rows[0]['TimestampUtc'])).total_seconds()/86400) if len(rows)>1 else 0
    coverage = (len(rows)/expected_completed) if expected_completed else 0
    ready = (len(dates) >= min_days and span_days >= min_days-1
             and coverage >= 0.80 and freshness_minutes is not None and freshness_minutes <= 90)
    report = {
       'Version':VERSION, 'Status':'READY' if ready else 'INSUFFICIENT_HISTORY',
       'GeneratedUtc':now.isoformat(), 'ReadOnly':True,
       'Measurement': 'inferred household demand from grid + PV - battery-charge',
       'SignConvention': 'grid +import/-export; battery +charge/-discharge',
       'HistoryStartUtc':cutoff.isoformat(), 'HistoryEndUtc':now.isoformat(),
       'SamplesRead':len(points), 'InvalidSamples':invalid,
       'CompleteValidHalfHours':len(rows), 'ExpectedHalfHoursApprox':expected_completed,
       'ObservedHalfHourCoveragePct':round(100*len(rows)/expected_completed,1) if expected_completed else 0,
       'DistinctUKCalendarDays':len(dates), 'ObservedSpanDays':round(span_days,2),
       'MinimumCoveragePct':80.0, 'LatestValidHalfHourUtc':latest,
       'LatestValidHalfHourAgeMinutes':round(freshness_minutes,1) if freshness_minutes is not None else None,
       'RequiredSamplesPerHalfHour':min_points,
       'ReadyForSevenDayOptimisation':ready,
       'SevenDayCsv':str(folder/'HouseholdDemand7d.csv'),
       'Note':'Only completed observed intervals are exported; missing intervals are NOT invented.'}
    atomic_json(folder/'HouseholdTelemetryQuality7d.json', report)
    # Retain only 8d of raw readings, keeping the 7d report window intact.
    db.execute('DELETE FROM telemetry WHERE timestamp_utc < ?',
               ((now-dt.timedelta(days=8)).isoformat(),))
    db.commit()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='192.168.0.8')
    parser.add_argument('--port',type=int,default=502)
    parser.add_argument('--unit',type=int,default=247)
    parser.add_argument('--timeout',type=float,default=5)
    parser.add_argument('--protocol-address',type=int,default=4,
        help='PDU start address for the 30005 block; match existing proven FC04 reader')
    parser.add_argument('--data-dir',type=Path,default=DEFAULT_DIR)
    parser.add_argument('--max-kw',type=float,default=25.0)
    parser.add_argument('--min-points',type=int,default=4)
    parser.add_argument('--min-days',type=int,default=7)
    parser.add_argument('--export-only',action='store_true',help='Rebuild CSV from SQLite; no network call')
    args = parser.parse_args()
    if not (1 <= args.unit <= 247 and 1 <= args.min_points <= 6 and 1 <= args.min_days <= 7):
        parser.error('Invalid unit / minimum sample count / minimum days')
    now=utcnow()
    args.data_dir.mkdir(parents=True,exist_ok=True)
    with open_db(args.data_dir/'HouseholdTelemetry.sqlite') as db:
        if not args.export_only:
            sample=validate_sample(read_plant(args.host,args.port,args.unit,
                 args.timeout,args.protocol_address),args.max_kw)
            store(db, now.isoformat(),sample)
            print(json.dumps({'TimestampUtc':now.isoformat(),**sample},sort_keys=True))
            if not sample['valid']:
                print('WARNING: invalid reading stored; excluded from demand CSV',file=sys.stderr)
        report=export(db,args.data_dir,now,args.min_points,args.min_days)
        print(json.dumps(report,indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print(f'ERROR: {type(e).__name__}: {e}',file=sys.stderr)
        sys.exit(1)
