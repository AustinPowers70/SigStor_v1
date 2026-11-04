# Phase 3B supervised commissioning gates — RC20

The injectable execution engine is ready for independent hardware-in-the-loop integration, **not live release**.

1. Independent failsafe: demonstrate end-to-end inverter-neutralisation on loss of Thor service, LXC/host and LAN connectivity; validate that the independent supervisor can reach the inverter over a surviving path or that inverter-native timeout exists. Record expiry, worst-case latency, network topology and how the supervisor retains power. Failure of the independent path must prevent the session starting.
2. Authority: distinct operator session approval, exclusive lock, manual ownership, stopped/verified authority-panel service; never transform research-only RC13 output into an execution grant.
3. Qualification: fresh RC13/R5/R6 pair, one active slot, immutable fingerprint and matching action, exact commissioned power, SOC ceiling and export reserve; no action outside horizon.
4. Measurements: real FC04 30005 block at <=2-second intervals, timestamp and gap validation, battery-port and aggregate grid direction verified separately. Aggregate grid meter evidence does not identify battery-attributable delivery.
5. Fault-injection: verify handling of uncertain write response, loss of recovery liveness, loss of telemetry, control authority contention, clock discontinuity, source change and expiry.
6. Stop: zero PCS demand, restore self-consumption, disable Remote EMS; readback all three. If unverified, keep panel isolated, escalate to operator manual recovery. Never touch register 40034.
7. Release: after all gates, require a new explicitly operator-authorised short integrated live validation before any full-duration supervised slot; write-enabled deployment is not provided by RC20.
