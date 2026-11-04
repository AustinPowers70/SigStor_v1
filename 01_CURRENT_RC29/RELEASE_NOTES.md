# SigenStor Phase 3B RC23 — Thor-only operator-attended pulse integration

**No live operator command exists in this release.** RC23 is a Python-injected testable integration core for the previously commissioned **30-second** charge/export pilot setpoints (500 W/650 W). The full-slot RC22 path is retained but blocked; no autonomous dispatch. RC13 economic optimiser remains frozen.

The user elected not to deploy a second independent Linux supervisor. RC23 therefore **does not claim host-loss recovery**. It separates brief, physically operator-attended *commissioning research* from full-duration operation and forbids promoting a simulated predicate to physical proof.

RC23 adds: strictly 30-second bounded sessions; short-expiry manual permit; repeated operator-presence and qualification probes; exclusive-writer lock; isolation of authority panel; persistent latch BEFORE first write attempt; 2-second telemetry sampling with stale/SOC/reserve guards; verified readback handback; retained latch and panel isolation on ambiguous handback; explicit grid-side attribution caveat. All actions are injectable test adapters: there is no publicly invokable Modbus dispatch path, service change, timer, permission change or scheduled write.

**Unresolved acceptance:** No direct real plant binding, no proven recovery from total Thor/NAS/network loss, no full-slot physical energy direction confirmation. A 30-second test on a real plant requires separate explicit operator approval and a live commissioning release. Operator presence alone cannot stop a persistent power command after loss of Thor. Register 40034 must never be touched.
