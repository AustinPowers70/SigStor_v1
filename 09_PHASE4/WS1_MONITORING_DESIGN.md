# WS1: Read-only monitoring and alerting (design specification)

**Status:** design for review; nothing is implemented yet. **Read-only:** FC03/FC04 only, no writes, no service control, no dispatch.
**Purpose:** detect and announce states that matter for safety, above all **Remote EMS active with no live session** (the visible symptom of L1 and L5), and **Thor itself going silent**.

## 1. Components
| Component | Runs on | Function |
|---|---|---|
| `plant_monitor_ws1.py` | Thor, systemd service (Restart=always, no timer-driven writes) | Polls the plant every 10 s using `commissioning_preflight_rc18.inspect()` and `power_acquisition_rc9.sample_once()` (reused, unchanged). Evaluates rules (§3) and writes `/opt/sigenstor/data/monitor/state.json` (atomic replace) and `monitor-events.jsonl` (append). |
| Dashboard panel | Existing nginx dashboard `:8088` | Read-only view of `state.json`: plant registers, SOC and power, latch, controller-lock holder, last session status, restrictions in force, commissioning status. **No control buttons.** |
| Push notifier | Thor | Sends rule transitions (raise and clear) to the chosen channel (ntfy, Pushover or email). Rate-limited, with repeat reminders for unresolved CRITICAL alerts. |
| External dead-man's switch | Off-Thor free service (e.g. healthchecks.io-style) | The monitor pings it every cycle. **No ping for 3 minutes means the service alerts the operator directly**, covering loss of Thor, Proxmox, the LXC, the network or the monitor itself. |

## 2. Design constraints
- **The monitor must never contend with a live controller.** Modbus reads go over a separate TCP connection, the same way the RC27 observer already does without trouble during E1 and E3. The monitor **never calls flock** on `/run/lock/sigen-rtm-v12-commission.lock`, not even briefly. The controllers and the RC29b closure tool take the lock with `LOCK_NB`, so even a momentary probe could make a legitimate session refuse to start. The monitor finds the lock holder **only** by matching the lock file's inode in `/proc/locks`, which never takes the lock.
- **Read cadence:** the plant tolerated the observer's 2 s cadence alongside the controller during pilots. The monitor runs at 10 s and drops to 2 s while a session is active (lock held), to give evidence continuity.
- **Fail-loud:** a monitor exception or a failed read is itself an event. Three consecutive read failures raise `TELEMETRY_STALE`.
- **No dependency on RC13** or price data; the monitor doesn't touch the frozen optimiser.
- **Secrets:** the notifier token lives in a root-only file outside the repo.

## 3. Rules
"Session active" means the controller lock is held, or a latch exists whose session has no `SESSION_RESULT` yet.

| ID | Condition | Severity | Notes |
|---|---|---|---|
| M1 | 40029 ≠ 0 **and no session active** for 2 consecutive polls | **CRITICAL** | Primary L1/L5 symptom: plant under remote control with nobody owning it. Action: runbook §5. |
| M2 | 40031 ≠ 2 or 40001 ≠ 0, with no session active | CRITICAL | Mode or PCS demand left set. |
| M3 | Recovery latch present | WARNING (CRITICAL if > 15 min and no session active) | A latch left after a session needs a decision. |
| M4 | Session active for longer than the commissioned bound + 60 s (currently 30 s + 60 s) | CRITICAL | Overrun; covers a hung delegate. |
| M5 | SOC < SoftReserve | WARNING | Reserve protection visibility. |
| M6 | Telemetry stale (3 failed polls) or `valid=false` on 5 consecutive samples | WARNING | Separates comms faults from plant faults. |
| M7 | Authority panel inactive with no session active | WARNING | Covers a restart withheld after CRITICAL handback. |
| M8 | Dead-man ping missing (evaluated **off-Thor**) | CRITICAL | Thor or the monitor is down. If a session might have been active, use MySigen recovery. |
| M9 | New `CRITICAL_*` line in `phase1-supervised-audit.jsonl` | CRITICAL | Relays controller-raised criticals. |

## 4. Limits (stated, not hidden)
- **The monitor detects; it doesn't recover.** Recovery stays with the human, through MySigen (runbook §5), until WS2 delivers something better.
- **M8 tells you that Thor is gone, not what state the plant is in.** If Thor is down, the plant state has to be checked in MySigen.
- If the inverter's Modbus server is unreachable but Thor is up, M6 fires but M1 can't be evaluated.

## 5. Tests and acceptance (G1)
- **Offline:** unit tests for each rule with injected `inspect`/`sample` fakes, lock-holder detection via `/proc/locks` (test asserts no `flock` call is ever made on the controller lock), atomic state writes, and notifier rate limits.
- **Live (read-only, operator-approved):**
  - run for an agreed observation period with no false CRITICAL alerts;
  - **M8 drill:** stop the monitor service and confirm the off-Thor alert arrives;
  - **M3/M7 drills** with a test latch path and panel stop/start (no plant writes).
- M1 and M2 are tested offline only. Exercising them live would need a plant write, which is out of scope unless it's combined with an approved pilot (e.g. watching M1 stay quiet while the lock is held).

## 6. Operator decisions needed
1. Alert channel (ntfy, Pushover or email) and the off-Thor dead-man service.
2. Confirm the 10 s / 2 s poll cadence is acceptable for the inverter.
3. Confirm that showing plant registers, SOC and power on the dashboard behind the existing nginx auth is acceptable (no change to auth proposed).
