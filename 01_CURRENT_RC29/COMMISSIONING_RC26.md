# RC26 — Physical commissioning evidence capture (READ ONLY)

## Why this package

RC25 (314/314 on Thor) already validates simulation and audit ordering. The missing evidence is a time-aligned physical power trace when an experienced operator elects to use the **previously commissioned** operator-driven pilot. RC26 installs an actual 1–2 s FC04 passive capture and quantitative assessor, not another simulated actuation release.

The package **does not actuate the inverter** and cannot run a pilot. It does not add any timer or service. Source RC13 remains unchanged. No 40034 writes. Do not claim physical battery-attributable grid-side energy from a battery-port and an aggregate-grid trace alone.

## Independent read-only plant check

`python3 -B /opt/sigenstor/scripts/phase3b-supervised-rc26/controller/commissioning_preflight_rc18.py --check`

## Read-only capture, with operator supervising MySigen

`python3 -B /opt/sigenstor/scripts/phase3b-supervised-rc26/controller/commissioning_capture_rc26.py --capture --seconds 75 --file /opt/sigenstor/data/rtm/rc26-pilot-20261104T1800Z.jsonl`

A separate, operator-approved, previously commissioned 30-second pulse would occur only after an explicit live-plant commissioning decision. The record command never initiates it. Capture starts before the pulse and continues past handback. Choose a *new unique* filename per session; RC26 will not overwrite evidence. Since 75 seconds of capture is timed, launch/coordinate separate operator control as appropriate. Independent Thor-loss recovery is not provided.

## Assessment

`python3 -B /opt/sigenstor/scripts/phase3b-supervised-rc26/controller/commissioning_capture_rc26.py --assess --file /opt/sigenstor/data/rtm/rc26-pilot-20261104T1800Z.jsonl`

Signed battery port: positive charging, negative discharging in the original FC04 decoder; grid positive importing, negative exporting. The battery-port Wh and aggregate-grid Wh are *separate* integrations, not one proven meter-side energy flow. Samples separated >6 seconds are excluded from integration; a coverage/gap hold prevents unwarranted acceptance. The actual physical pilot times and pre/post handback readbacks must also be correlated before declaring success.

## Commissioning boundary

A full-duration or unattended session is NOT authorised. A shorter manual-attended real pulse has nonzero risk of continued Remote EMS actuation if Thor or its network fails at the wrong moment. Live operations require a new explicit operator decision; staging this bundle does not grant that consent.
