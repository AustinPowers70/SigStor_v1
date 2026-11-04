# Thor-only commissioning decision — 4 November 2026

## Chosen scope
No independent Linux recovery supervisor is to be installed. The separate prototype is retired from the active workstream. Keep RC22 as rollback and RC23 as candidate for short physically supervised commissioning tests. This changes *scope*, not the physics of uncontrolled network or host loss.

## Commissioning sequence (not yet performed)
1. Operator checks physical plant and MySigen and explicitly authorises one 30-second pulse. Confirm operator has an independent way to end Remote EMS if Thor disappears; otherwise keep actuation disabled.
2. Ensure 40029=0, 40031=2, 40001=0, only one writer, exclusive manual authority, valid SOC/soft reserve, no charge above 95%; ensure 40034 unchanged.
3. Run one limited, monitored trial with sustained observations at about two seconds and a durable audit; freeze further trials after any uncertain handback.
4. Confirm PCS=0, mode=2, Remote EMS=0, correlate actual battery/grid observations; do not claim aggregate grid indicates battery-attributable energy.
5. Only after acceptance decide whether longer than 30-second runs are tolerable under the host-loss risk. Full-slot sessions remain blocked without a risk resolution specifically accepted by the operator.

## Important boundary
The RC23 Python engine is INJECTION ONLY and cannot physically actuate the inverter from an installed CLI. There is no new approval prompt needed for read-only engineering, but live writes require explicit approval.
