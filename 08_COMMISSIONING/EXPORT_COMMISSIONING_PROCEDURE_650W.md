# Operator-attended EXPORT commissioning: 650 W, 30 s (RC28 entry point, RC29b verdict and closure)

**Status:** offline-reviewed, ready for independent review. **No live execution without explicit operator approval for this session.**
**No code change was required.** Use the installed `/opt/sigenstor/scripts/phase3b-supervised-rc29/` tree, which already contains the RC29b verdict separation and closure tool.

## 1. What the code will do (verified offline against a recording fake inverter)
Entry: `attended_commissioning_rc28.py --execute EXPORT --operator-ack`. This is the RC27 orchestrator, which delegates through a one-shot FD grant to the `commissioning_controller_rc28.py` child, which calls `supervised_export.perform_export`.

1. **Preflight (read-only):** RC28 permit `EXPORT`.
   - MANUAL authority file (`requested=MANUAL`, `dispatch_authorised=false`, `remote_ems_verified_off=true`).
   - Plant handed back (40029=0, 40031=2, 40001=0 as two words).
   - `SoftReserve+2 ≤ SOC ≤ 98`.
   - Authority panel active.
   - The permit runs before the TTY challenge and again after it.
2. **Latch armed:** `rc28-recovery-required.json`, before any actuation. The 2 s FC04 observer starts with a BEFORE baseline of at least 2 samples.
3. **Child takes ownership:**
   - Takes the exclusive flock `/run/lock/sigen-rtm-v12-commission.lock`.
   - Stops `sigen-rtm-authority-panel.service` and verifies it's stopped.
   - Re-qualifies.
   - Live checks: 40029 must be 0; SOC must be within `reserve+2…98`.
4. **Writes, exactly:** `40029=1`, then `40031=0` (PCS remote control), then `40001=650` (U32). 40029 is read back as 1.
5. **30 s hold:** every 2 s, SOC is checked against `reserve+2` and the permit is re-checked (ACTIVE stage). Any failure aborts to handback.
6. **Handback** (any exit after the first write attempt, including a timeout on the first write):
   - Writes `40001=0`, then `40031=2`, then `40029=0`.
   - Verifies 40029=0, 40031=2 and 40001 two-word zero.
   - Up to 3 attempts.
   - On failure: `CRITICAL_EXPORT_HANDBACK_UNVERIFIED`, the panel is **left isolated**, and the child exits non-zero.
7. **Parent:** AFTER samples, then an independent read-only preflight and panel check.
   - Both clean: latch auto-clears.
   - Handback proven but telemetry degraded: `HOLD_EVIDENCE_REVIEW_HANDBACK_VERIFIED`, closable with RC29b.
   - Otherwise: `HOLD_RECOVERY_REQUIRED`.
8. **Never written:** 40034, 40032. No timers, no RC13 involvement.

Offline simulation results (`sim_export_path.py`):
- Nominal sequence correct.
- SOC drop below the margin mid-pulse aborts and hands back.
- A timeout on the first write still hands back.
- Handback refusal raises CRITICAL and keeps the panel isolated.
- 40034 is never touched in any scenario.

## 2. Open points the reviewer and operator must accept before approval
| # | Point | Disposition |
|---|---|---|
| A | **Sign of 40001 is not evidenced in the repo.** "Previously commissioned 650 W" refers to a Phase-1 record that isn't in the handover. Scaling is consistent with the working charge pilot (40032=500 gave about 0.5 kW). | Low physical hazard either way: a wrong sign means a 0.65 kW charge for 30 s, the same class as E1. The pilot itself establishes the sign. The summariser warns if the battery charges. |
| B | **What 40001 controls is not established:** inverter/PCS output (H1) or grid connection point (H2). With household load at L kW, H1 gives battery ≈ −0.65 kW and grid ≈ L−0.65 (**likely still importing**). H2 gives grid ≈ −0.65 and battery ≈ −(L+0.65). | Both stay within limits: worst case battery discharge is L+0.65 kW (under 8 kW unless house load exceeds about 7.3 kW), and 30 s is at most about 0.2 % SOC. **Acceptance does not require grid export.** It requires response consistent with H1 or H2. |
| C | **Operator Ctrl-C mid-pulse:** the child's `finally` still runs handback, but the parent records no `SESSION_RESULT`, so RC29b cannot close the latch. | Fails closed. Use MySigen for intervention; avoid Ctrl-C unless it's an emergency. A stuck latch would then need a reviewed code extension (not built; not needed for nominal operation). |
| D | Lock and panel isolation exclude **cooperating** writers only; no host-loss recovery. | Unchanged standing limitation; operator stays attended with MySigen manual control. |
| E | Phase-boundary sample labelling race in RC27. | Only effect: a review fails closed. |

## 3. Procedure (all blocks start with `clear`)
**Before you start:** MySigen open on a device not dependent on Thor. Choose a period with **stable, preferably low (<1 kW) household load**; avoid switching kettle, oven or shower. This reduces H1/H2 ambiguity and `home_kw` artefacts. SOC comfortably above reserve+2 %.

**Step 1: read-only readiness (approve as read-only):**
```bash
clear
cd /opt/sigenstor/scripts/phase3b-supervised-rc29/controller
sudo python3 -B latch_closure_rc29.py --status
sudo python3 -B commissioning_preflight_rc18.py --check
sudo python3 -B attended_commissioning_rc28.py --check EXPORT
sudo cat /opt/sigenstor/data/control-authority.json /opt/sigenstor/data/SoftReserveSettings.json
```
Proceed only if:
- the latch is `ABSENT`;
- preflight shows `plant_handback_verified: true`;
- `--check EXPORT` returns `READONLY_ELIGIBLE`;
- the authority file is MANUAL, not authorised for dispatch, with Remote EMS verified off.

**Step 2: LIVE (only after explicit operator approval for this session):**
```bash
clear
cd /opt/sigenstor/scripts/phase3b-supervised-rc29/controller
sudo python3 -B attended_commissioning_rc28.py --execute EXPORT --operator-ack
```
Type exactly `AUTHORISE EXPORT 30 SECONDS`. Watch MySigen for 30 s: battery should discharge and the plant should return to self-consumption afterwards.
**Intervene in MySigen** (not Ctrl-C) if: the battery charges at more than about 1 kW, discharge exceeds about L+1 kW, or the inverter doesn't return to self-consumption within about 60 s of the start.

**Step 3: evidence (read-only):**
```bash
clear
sudo python3 -B commissioning_preflight_rc18.py --check
sudo ls -t /opt/sigenstor/data/rtm/rc27-pilot-*.jsonl | head -1 | xargs sudo python3 -B /tmp/copy-paste/summarise_pilot_trace.py
sudo tail -5 /opt/sigenstor/data/rtm/phase1-supervised-audit.jsonl
```
- `SUPERVISED_PILOT_HANDBACK_CONFIRMED`: latch already cleared; record the evidence.
- `HOLD_EVIDENCE_REVIEW_HANDBACK_VERIFIED`: run `latch_closure_rc29.py --review`, then `--close --operator-ack` with MySigen witness (the same procedure as E2).
- `HOLD_RECOVERY_REQUIRED` or any CRITICAL: **stop.** Confirm in MySigen that Remote EMS is off and the plant is in self-consumption. Send me the output. Don't clear anything.

## 4. Acceptance criteria (declared before the test)
1. Controller exit 0, lifecycle complete, handback verified by the controller **and** by the independent post-preflight; panel restored; 0 observer writes.
2. DURING battery mean is negative, consistent with H1 (≈ −0.65 ± 0.15 kW) **or** H2 (grid ≈ −0.65 ± 0.15 kW). Record which one. If the battery charges, the sign is rejected and export is blocked pending review.
3. AFTER returns to the self-consumption pattern; SOC change is negligible.
4. MySigen observation recorded.

Not claimed: battery-attributable grid-side energy, host-loss recovery, readiness for full-slot or autonomous operation.
