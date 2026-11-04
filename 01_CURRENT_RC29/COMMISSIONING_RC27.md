# RC27 attended physical commissioning coordinator

**Operator-approved live writes possible only when running `--execute ACTION --operator-ack` and typing the exact action-specific approval locally.** Installation and `--check` perform no writes.

`--execute` delegates to the previously commissioned 30-second `controller.py` charge/export implementation. It does not add a new Modbus command sequence or enable timers. It requires an active valid RC13 action and MANUAL authority, prior handback, correct SOC, and the authority panel running. The existing legacy controller still performs the actual qualification and writes; its command path was previously commissioned at 500 W charging and 650 W PCS export. Never write 40034.

A durable RC27 recovery latch is armed before the child controller starts and is cleared only after the child exits successfully, real read-only postflight proves Remote EMS off/self-consumption/PCS-zero, the panel is active, and valid observation samples exist before, during, and after. Otherwise latch remains and needs supervised physical recovery review. **A recovery latch cannot restore control after physical host loss.** The earlier controller uses its own writer lock; RC27 does not override it. Legacy controller invocation outside RC27 is not blocked by this latch.

Telemetry phases are relative to the delegated controller's process lifetime, not a readback of the actual instant of Modbus actuation. Aggregate grid energy is not battery-attributable. Measured power and pilot event correlation require human commissioning review.

**Preflight (no writes):**

    python3 -B /opt/sigenstor/scripts/phase3b-supervised-rc27/controller/attended_commissioning_rc27.py --check GRID_CHARGE

Use `EXPORT` to check the export pilot. If no RC13 qualified slot exists, the result is a normal HOLD.

**Live pilot only during attended and specifically authorised physical commissioning:**

    python3 -B /opt/sigenstor/scripts/phase3b-supervised-rc27/controller/attended_commissioning_rc27.py --execute GRID_CHARGE --operator-ack

The command presents a TTY-specific confirmation phrase, samples read-only FC04 data during the pilot, and delegates the command to the previously commissioned operator-only controller. This is not permitted without an operator present, a recoverable plant, and explicit approval of residual Thor/network-loss risk. Stop at 30-second pilots; never use for 30-minute full-slot dispatch.

Physical recovery of an uncertain latch requires operator engineering assessment. No software bypass is supplied. Existing legacy code can still run separately; production consolidation must eliminate legacy bypass paths before wider deployment.
