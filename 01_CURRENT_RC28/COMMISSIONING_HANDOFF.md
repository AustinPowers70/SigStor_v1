# Phase 3B — Supervised commissioning handoff (RC19)

## Baseline
RC18 on Thor accepted: 226/226 offline tests; manual read-only live preflight at 2026-11-01T18:22:17Z confirmed 40029=0, 40031=2, PCS request zero, SOC 60.4%, battery -7.484 kW and aggregate grid +0.006 kW. No physical energy allocation verified. These readings are historical, not current.

## Development frozen
RC13 economics unchanged. All full-slot write entrypoints remain disabled. RC19 produces a current *read-only* assessment; it does not carry a live session token, transport writer, or dispatch flag. The existing 30-second supervised pilots must not be lengthened by direct calls.

## Outstanding gates before FULL-SLOT actuation
1. Obtain independently effective loss-of-host/network/Modbus communications recovery: an inverter-native bounded EMS timeout that has been **verified** in a safe commissioning test, or a genuinely independent supervisory device. An application timer inside the same Thor LXC is not independent recovery.
2. Commission real single-writer authority and exclusive lock ownership; hold the authority panel isolated until positive handback confirmation. Fail closed on handback ambiguity and retain documented operator manual recovery.
3. Bind the 500 W charge/650 W export command contract to session timing, per-sample SOC limits, active qualification and fixed slot expiry. The research-only RC13 source cannot directly authorise live control.
4. Obtain independently grounded grid-side evidence; aggregate grid flow plus battery-port flow alone does not prove delivery allocation. Use the installed two-second readings as supporting evidence; do not use interpolated gaps as actual samples.
5. Execute an operator-attended bounded integrated validation, followed by a qualified full-slot session only when all gates pass, with reviewed rollback and emergency manual handback procedures.

## Operational sequence
- Install this package only from /tmp/copy-paste; do not enable services/timers or start writes.
- Run the RC19 current readiness handoff with --check-plant only when no other session owns the inverter. This reads the plant, it never writes.
- `HOLD_FOR_SUPERVISED_COMMISSIONING` is expected until verified external recovery and the live actuator exist. DO NOT edit a JSON field to bypass the blocker.
- Approval to develop is not approval to dispatch. Each live operation requires an explicitly attended operator action and separate review.

## Rollback
The install is side-by-side with RC18 and changes no services. To remove this staged package, run its rollback.sh. Do not alter live plant state via rollback.
