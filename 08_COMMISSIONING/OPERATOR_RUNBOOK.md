# Operator runbook: current operating rules (after Phase 3B closeout)

Applies from 2026-11-04 until changed by explicit, reviewed operator decision. Source: `PHASE3B_CLOSEOUT_REPORT.md` §5.
Installed tree: `/opt/sigenstor/scripts/phase3b-supervised-rc29/controller`. Staging: `/tmp/copy-paste/` only. Every shell block starts with `clear`.

## 1. Hard rules
| Rule | |
|---|---|
| Live writes | Only with explicit operator approval **for that session**. Earlier approvals never carry over. |
| Allowed actions | `GRID_CHARGE` 500 W / 30 s and `EXPORT` 650 W / 30 s, attended, via RC28 `--execute … --operator-ack`. Nothing else. |
| Forbidden | Longer durations, other setpoints, timers or schedules, unattended runs, autonomous dispatch, any 40034 write, editing RC13, deleting a latch by hand. |
| Supervision | MySigen open on a device that **doesn't depend on Thor**. Intervene in MySigen, **not** with Ctrl-C (see §5). |
| Evidence | Keep `rc27-pilot-*.jsonl`, `phase1-supervised-audit.jsonl` and `rc29-latch-closures/`. Never edit them. |

## 2. Read-only status check (safe at any time; makes FC03/FC04 reads only)
```bash
clear
cd /opt/sigenstor/scripts/phase3b-supervised-rc29/controller
sudo python3 -B latch_closure_rc29.py --status          # no plant access
sudo python3 -B commissioning_preflight_rc18.py --check # read-only Modbus
```
Healthy idle state: latch `ABSENT`, `remote_ems_off: true`, `self_consumption: true`, `pcs_zero: true`, `plant_handback_verified: true`.

## 3. Running a commissioned pilot (only with fresh approval)
Use `EXPORT_COMMISSIONING_PROCEDURE_650W.md` §3. For charge, use the same steps with `GRID_CHARGE`; the TTY phrase is `AUTHORISE GRID_CHARGE 30 SECONDS`. Summarise with `08_COMMISSIONING/tools/summarise_pilot_trace.py`. Record each run in `COMMISSIONING_EVIDENCE.md`.
Known behaviour:
- **Charge:** household load moves to the grid while charging.
- **Export:** the 650 W is at the inverter side, so net grid export = 650 W − household load. It can be zero or even import.

## 4. Outcome handling
| Result status | Meaning | Action |
|---|---|---|
| `SUPERVISED_PILOT_HANDBACK_CONFIRMED` | Clean; latch auto-cleared | Record evidence. |
| `HOLD_EVIDENCE_REVIEW_HANDBACK_VERIFIED` | Plant handed back; telemetry degraded | `latch_closure_rc29.py --review`, then `--close --operator-ack` with MySigen witness. If the review isn't eligible, stop and escalate. |
| `HOLD_RECOVERY_REQUIRED` | Handback not proven | **Stop.** Use §5. Clear nothing. |
| `RC28_FAIL_CLOSED` / `RC27_FAIL_CLOSED` | Refused or failed. If before the latch was armed, no writes. | Read the reason. Run §2. If a latch exists, treat it as `HOLD_RECOVERY_REQUIRED`. |

## 5. Incident response: plant possibly not handed back
Triggers include:
- a CRITICAL message (`CRITICAL: … handback unverified`, `authority panel remains isolated`);
- Thor, Proxmox or the network lost during a pulse;
- a Ctrl-C during a pulse;
- MySigen showing remote control or an unexpected charge/discharge.

1. **In MySigen:** confirm or restore self-consumption mode and that remote/third-party EMS control is off. This is the primary recovery path whenever Thor is unavailable.
2. **When Thor is reachable,** run §2 read-only. Repeat until `plant_handback_verified: true` on several consecutive reads.
3. **Leave the authority panel stopped** if the controller withheld its restart. Restart it only after step 2 passes: `sudo systemctl start sigen-rtm-authority-panel.service`.
4. **Don't delete the latch** and don't start another session. Keep the trace and audit, and send the output for engineering review.
   - If the session has no `SESSION_RESULT` (Ctrl-C, or Thor lost mid-pulse), RC29b **can't** close it. That's limitation L5, and it needs the reviewed WS2 abort extension.

## 6. What is NOT protected
- Recovery if the host goes down (L1).
- Writers that don't cooperate with the lock (L2).
- Metered energy attribution (L3).

See the closeout report §4 for the full list.
