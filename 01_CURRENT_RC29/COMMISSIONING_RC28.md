# RC28 — commissioning-only permit (operator-attended, no economic slot required)

The existing RC13 economic qualification is **unchanged** for tariff/trading operation. RC28 adds a separate manual 30-second physical commissioning qualification that uses MANUAL authority, verified Remote EMS off, self-consumption/PCS zero, SOC and reserve guards, authority-panel health and durable recovery latch, with explicit local TTY confirmation. It reuses the commissioned 500W charge and 650W export routines and RC27 event/2s power capture. It requires **no current RC13 economic slot**.

## Non-actuating preflight

    python3 -B /opt/sigenstor/scripts/phase3b-supervised-rc28/controller/attended_commissioning_rc28.py --check GRID_CHARGE

## Live commissioning

NOT authorised by installation or by these instructions. Do not run without explicit operator decision, MySigen monitoring, manual recovery capability and acceptance of the host-loss handback exposure. If separately approved, command is `--execute GRID_CHARGE --operator-ack` with local action-specific TTY phrase. No timers/service changes. A successful 30-second pulse is not full-slot acceptance.

## Restrictions

- Charge 500 W for 30 seconds; export 650 W for 30 seconds; no 40034.
- Local Modbus writer lock and temporary authority-panel isolation; safety latch is armed before delegation.
- Normal controller `qualify()` and export `qualify_export()` are unchanged by default.
- If the operator/Thor/network disappears during actuation, guaranteed handback is **not** established.
- No autonomous dispatch, no overnight schedule modification, no long-duration control.
- Legacy controller bypass is still possible and requires consolidation before a production system.
