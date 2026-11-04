#!/usr/bin/env python3
"""Publish existing read-only SigenStor planner telemetry."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path("/opt/sigenstor/data/LatestSchedule.json")
DEST = Path(
    "/opt/sigenstor/web/beta/live-preview/telemetry.json"
)

def fail(message):
    raise RuntimeError(message)

if SOURCE.is_symlink() or DEST.is_symlink():
    fail("Unexpected symbolic link")

with SOURCE.open(encoding="utf-8-sig") as handle:
    schedule = json.load(handle)

soc = schedule.get("BatterySoc") or {}
meter = (schedule.get("Metering") or {}).get("Instantaneous") or {}

for key in (
    "GridNetW",
    "BatteryW",
    "EstimatedHouseLoadW",
    "TimestampUtc",
):
    if meter.get(key) is None:
        fail("Missing measurement: " + key)

if soc.get("Percent") is None:
    fail("Missing SOC")

# Never replace a valid snapshot with null or
# malformed telemetry.
soc_value = float(soc["Percent"])
if not 0 <= soc_value <= 100:
    fail("SOC outside valid range")

for key in ("GridNetW", "BatteryW", "EstimatedHouseLoadW"):
    value = float(meter[key])
    if not -20000 <= value <= 20000:
        fail("Power measurement outside sanity limits")

payload = {
    "Schema": "sigen.beta.telemetry.v1",
    "SnapshotCreatedUtc": datetime.now(timezone.utc).isoformat(),
    "PlannerGeneratedUtc": schedule.get("GeneratedUtc"),
    "MeasurementUtc": meter["TimestampUtc"],
    "SocReadUtc": soc.get("ReadUtc"),
    "SocPercent": soc_value,
    "GridNetW": meter["GridNetW"],
    "BatteryW": meter["BatteryW"],
    "EstimatedHouseLoadW": meter["EstimatedHouseLoadW"],
    "PvW": meter.get("PvW", 0),
    "Source": "Existing read-only planner output",
    "AutomaticSnapshotRefreshEnabled": True,
    "InverterDispatchEnabled": False,
}

# Atomic replacement: browser never sees partially
# written JSON. Preserve destination ownership.
owner = DEST.stat()
temporary = None

try:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=DEST.parent,
        prefix=".telemetry-",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())

    os.chown(temporary, owner.st_uid, owner.st_gid)
    os.chmod(temporary, 0o640)
    os.replace(temporary, DEST)
finally:
    if temporary and temporary.exists():
        temporary.unlink()

print(
    "PASS: telemetry refreshed | "
    f"SOC={soc_value:.1f}% | "
    f"grid={meter['GridNetW']}W | "
    f"battery={meter['BatteryW']}W"
)
