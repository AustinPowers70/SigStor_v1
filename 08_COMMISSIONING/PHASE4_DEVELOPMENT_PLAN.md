# Next-phase development plan (Phase 4): safe bounded operation, then monitoring, recovery and tariff integration

**Status:** PROPOSAL for independent review. Nothing here is authorised until the operator approves it. Each workstream ends at a gate that needs an explicit decision.
**Constants throughout:**
- RC13 frozen (new planning work runs **alongside** it, never inside it).
- Autonomous dispatch disabled.
- 40034 never written.
- Every live write is approved per session.
- No unattended execution until G5 below, a separate future decision.

**Working method** (based on the lessons from RC1–RC28):
- One consolidated, reviewed package per workstream, not chains of near-identical RCs.
- Offline tests aimed at changed behaviour, plus a short full-suite sanity run.
- The repository becomes the single source of truth before more code is written.

---

## Priority order and rationale
The dominant unresolved hazard is **L1: Remote EMS left active after Thor is lost.** Any increase in duration lengthens the window in which that can happen. So **recovery and monitoring come before bounded-duration growth**, and tariff integration stays read-only and advisory until both are in place.

| Order | Workstream | Live writes? | Gate |
|---|---|---|---|
| WS0 | Repository baseline and live-source capture | None | G0 |
| WS1 | Read-only monitoring and alerting | None | G1 |
| WS2 | Recovery arrangements and worst-case hazard analysis | Attended drills only, if approved | G2 |
| WS3 | Bounded-session operation (step-wise duration increase) | Attended, approved per session | G3 (per step) |
| WS4 | Metering and energy attribution | None | G4 |
| WS5 | Tariff integration: advisory, then operator-approved | None, then attended per slot | G5a / G5b |
| — | Unattended or autonomous dispatch | — | Separate future project; not in this plan |

---

## WS0: Repository baseline and live-source capture (fixes L9)
1. Run `06_THOR_COLLECTION/collect_thor_source_readonly.sh` on Thor. Commit `/opt/sigenstor/scripts` (excluding secrets, databases and traces) as `08_THOR_LIVE_SOURCE/`, along with `systemctl list-timers` and unit files.
2. Diff the live tree against the repo, and identify:
   - the Octopus sync, the advisory planner, nightly optimiser and RC13 producer;
   - **every program that can write to Modbus**, which is input to L2.
3. Secrets hygiene: keys stay in a root-only file on Thor. Add a pre-commit secret scan. Because the repo is public, also scan the history.
4. Record a deployment manifest: the installed tree, active units and timer modes.

**G0 exit:** the repo matches Thor; the writer inventory is complete; no secrets in the history.

## WS1: Read-only monitoring and alerting
1. **Plant-state monitor:** a read-only FC03/FC04 poller that reuses `inspect()` and `sample_once()`, with its own lock-free read path. It publishes Remote EMS, mode, PCS demand, SOC, power, latch state, last session and lock holder to the existing dashboard (`:8088`).
2. **Anomaly rules:**
   - Remote EMS ON with no live session holding the controller lock;
   - mode ≠ 2 outside a session;
   - latch present;
   - SOC below reserve;
   - telemetry stale.
3. **Alerting off Thor:** push notifications (ntfy, Pushover or email) so you're alerted by something that doesn't depend on Thor staying healthy for the alert to *reach* you. A heartbeat-absence alert from an external free service (a dead-man's switch) detects that Thor itself has gone silent.
4. **Web-panel status:** show the restrictions in force and the commissioning status. No control actions are added to the web UI.

**G1 exit:** monitoring has run for an agreed observation period. Alerts are shown to reach you for each rule, by simulation plus one real "Thor heartbeat stopped" test (stop the service; no plant writes).

## WS2: Recovery arrangements (L1, L5, L2)
The operator has rejected an independent Linux recovery host, so this workstream looks for other ways to bound the hazard:
1. **Inverter-native fallback (research first).** Find out from Sigenergy documentation or support whether the EC 8 SP has a Modbus communication-loss timeout or a Remote EMS watchdog that reverts to self-consumption. **I'm not assuming it exists.** If it does, plan an attended, approved drill: start a 30 s pilot, block Thor's network, and observe the plant revert.
2. **Worst-case stuck-state analysis (offline plus documentation).** For each commissioned mode, characterise what happens if the setpoint persists indefinitely:
   - charge until what SOC, at what cost;
   - discharge until which BMS/backup SOC (as configured in MySigen, not via 40034).

   Then decide the **maximum tolerable stuck duration and power** that bounds WS3.
3. **MySigen override drill.** An attended, approved test showing that MySigen can take back control while Remote EMS is ON, with the time taken. This is the human recovery path L1 depends on.
4. **Operator-abort fix (L5).** The parent catches SIGINT, lets the child finish handback, and records `OPERATOR_ABORT`, `DELEGATE_EXIT` and `SESSION_RESULT`. Extend RC29b review to accept an operator-aborted session **only** with verified fresh handback. Tests plus independent review.
5. **Writer exclusion (L2).** Using the WS0 inventory, retire legacy write paths, or make them take the same lock and latch check.
6. **Thor resilience** (reduces, doesn't remove, L1): a systemd watchdog for the controller process, a UPS for the Proxmox host, and LXC auto-start.

**G2 exit:**
- A documented maximum tolerable stuck exposure.
- A tested recovery path (inverter-native or a MySigen drill) with measured time-to-recover.
- The L5 fix accepted.
- A writer inventory closed or mitigated.

## WS3: Bounded-session operation (step-wise, attended)
Generalise the 30 s pilots into one **bounded-session controller**:
- duration as a parameter, capped by G2's tolerable exposure;
- charge setpoint ≤ an approved cap, export setpoint ≤ an approved cap;
- per-sample SOC, telemetry-gap and power-plausibility aborts;
- a heartbeat file the WS1 monitor checks;
- the same latch, lock, panel isolation and verified handback;
- the evidence trace and RC29b verdict and closure.

It replaces the fixed `seconds != 30` guard with an **approved-envelope file**, root-owned and changed only by operator action, which lists the allowed durations and powers.

Step ladder (each step is a separate attended, approved session and **gate G3.n**; stop at any failure):

| Step | Duration | Charge / export setpoint | Purpose |
|---|---|---|---|
| 3.1 | 2 min | 500 W / 650 W | Longer-hold stability, telemetry cadence |
| 3.2 | 5 min | 500 W / 650 W | SOC-guard behaviour visible |
| 3.3 | 5 min | 2 kW / 2 kW | Power scaling, household interaction |
| 3.4 | 30 min (one Agile slot) | an approved value within G2 exposure | Full-slot behaviour, attended |

Export setpoints must account for L4: the setpoint is inverter-side, so net export = setpoint − household load.

**G3 exit (per step):** exit 0, verified handback, evidence accepted, and no monitoring anomalies.

## WS4: Metering and energy attribution (L3)
1. Read-only Octopus consumption API: half-hourly import and export for the MPAN, with the key kept local. Correlate WS3 sessions against meter intervals.
2. Check whether the inverter exposes cumulative import/export or charge/discharge energy registers (read-only) for finer attribution.
3. Define an attribution method, e.g. a counterfactual household baseline, with stated uncertainty. Feed it into `slot_commitment.py` so `delivered_grid_kwh` can become a qualified input.

**G4 exit:** a documented attribution method with error bounds, validated on several WS3 sessions.

## WS5: Tariff integration
**WS5a: advisory (read-only, no gate on plant):**
1. Ingest Agile import (`AGILE-24-10-01`) and Agile Outgoing (`AGILE-OUTGOING-19-05-13`) prices for the region from the existing sync, found in WS0.
2. **New deterministic planner, alongside frozen RC13:**
   - cheapest-N charge slots within the 8 kW and 18 kWh limits;
   - an export opportunity only when export price exceeds the stored-energy cost basis plus round-trip losses plus a margin;
   - reserve from a household demand forecast plus a safety margin;
   - the planner models the inverter-side setpoint (L4).
3. Show the plan, the price comparisons and the rationale on the dashboard, and log every decision. Compare advisory decisions with RC13 output and with actual outcomes.

**G5a exit:** the advisory planner runs reliably over an agreed observation period, and the decision log has been reviewed.

**WS5b: operator-approved execution:**
- Each proposed slot raises an approval request.
- The operator approves an individual slot.
- The WS3 bounded-session controller executes it within the approved envelope, attended, with the full evidence trail.

**G5b exit:** a set of approved slots executed with accepted evidence and economic reconciliation through WS4.

## Explicitly NOT in this plan
- Unattended, scheduled or autonomous dispatch. That's a separate project needing a fresh hazard and recovery acceptance after G2–G5b.
- Unfreezing or modifying RC13. Only by explicit operator decision.
- Any write to 40034.

## Decisions requested from the operator and reviewer
1. Agree the priority order (WS0, then WS1, WS2, WS3, WS4, WS5).
2. Approve WS0 now (read-only collection, no plant interaction).
3. Choose the alerting channel for WS1.
4. Agree whether to contact Sigenergy support about a communication-loss fallback (WS2.1).
