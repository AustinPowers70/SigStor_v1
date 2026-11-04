# RC21 Recovery design / next commissioning gate

**State model:** IDLE → LATCH_ARMED → SESSION_ACTIVE → VERIFIED_HANDBACK → IDLE, or any failure → RECOVERY_REQUIRED.

**Interlock:** per-session durable O_EXCL latch before control attempt; on uncertain outcomes retain file. An independent observer must determine actual physical state. Do not remove the marker manually, or rely on process lock as recovery evidence.

**Not yet implemented:** externally hosted recovery supervisor with separately maintained power and communications, validated ability to zero PCS/set self-consumption/disable Remote EMS following a forced Thor/LXC/network outage, independent heartbeat-expiry testing, and proof-bound manual release. Modbus writer coordination across authority-panel and earlier pilots needs explicit system-wide enforcement.

**Release criteria:** independent recovery demonstration, wired real readback/audit, exclusive authority under failure, operator approval and monitoring, bounded live commissioning and grid-side evidence. This package intentionally has no live entrypoint.
