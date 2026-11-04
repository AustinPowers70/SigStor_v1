# Phase 3B closeout report: 30-second supervised charge/export functional commissioning

**Project:** SigenStor / Octopus Agile. **Host:** Thor (Proxmox LXC 192.168.0.251). **Plant:** Sigenergy SigenStor EC 8 SP, 18 kWh, 8 kW, no PV, Modbus 192.168.0.8:502 unit 247.
**Report date:** 2026-11-04. **Prepared by:** Claude (lead developer), for independent review.
**Disposition:** Phase 3B **functional commissioning scope CLOSED**, within the limits stated in §4–§5. Closing it **authorises no wider operation.**

---

## 1. Scope being closed
Operator-attended, single-shot, fixed **30-second** pilots on Thor, through the RC28 entry point with the RC29b verdict:
- `GRID_CHARGE` at 500 W (40032=500, 40031=3, 40029=1)
- `EXPORT` at 650 W (40029=1, 40031=0, 40001=650)

Each pilot required: explicit per-session operator approval, a local TTY challenge, MySigen supervision, a durable recovery latch, panel isolation, a single cooperating writer lock, 2 s FC04 correlation telemetry, and verified handback.

**Out of scope, NOT closed:** longer durations, other power levels, scheduled or unattended execution, tariff-driven dispatch, RC13 trading, grid-side energy attribution, and host-loss recovery.

## 2. Accepted evidence
Full detail is in `COMMISSIONING_EVIDENCE.md`.

| ID | Item | Session | Result |
|---|---|---|---|
| E1 | GRID_CHARGE 500 W / 30 s | `8d39f77fc0e244b69f79f0257b56ba07` | Accepted: command response (peak +0.508 kW battery), verified handback, panel restored. 1 invalid AFTER `home_kw` sample. |
| E2 | Latch closure for E1 | same | Accepted: RC29b operator-witnessed closure at 20:09:39Z. Lock held throughout; 3 fresh readbacks; 0 Modbus writes. |
| E3 | EXPORT 650 W / 30 s | `deff25df597a435a9f4d589e60a9b7f4` | Accepted: 0 invalid samples, exit 0, verified handback, latch cleared automatically. Battery −0.669 kW DURING; net grid −0.154 kW. |

**Engineering facts established:**
1. **Charge path:** 40032 (U32) is in raw watts. Mode 3 with Remote EMS on gives grid charging at the setpoint. Household load moves to the grid during charging.
2. **Export path:** 40001 (U32) is in raw watts, **at the inverter/battery side, not the grid connection point.** Positive means discharge. Net grid export ≈ setpoint − household load. With load above the setpoint, the grid still imports.
3. **Handback:** the sequence (40001=0 where used, then 40031=2, then 40029=0, with readback) works physically in both modes. Independent post-preflight confirmed it each time.
4. **Recovery latch:** it held through a real evidence defect (E1). It was closed by a reviewed, operator-witnessed procedure (E2), and it cleared automatically on clean evidence (E3).

## 3. Software baseline at closeout
- **Installed:** `/opt/sigenstor/scripts/phase3b-supervised-rc29/`. This is RC28 plus the RC29b verdict separation (`attended_commissioning_rc27.py`) and `latch_closure_rc29.py`.
- **Package:** `SigenStor_Phase3B_RC29b_Latch_Closure.zip`, SHA-256 `169cde997de5e2bc0fdbc35588bfdbc365fbe0e82c55782e4d67764cdcf3912d`.
- **Offline suite:** 394/394, confirmed by independent review. This is simulation only and isn't evidence of physical acceptance.
- **Unchanged:** RC13 economic optimiser (frozen); autonomous dispatch disabled; 40034 never written; no timers or services added for actuation.
- **Repository:** `01_CURRENT_RC29/` (source) and `08_COMMISSIONING/` (evidence, procedure, this report, tools).

## 4. Outstanding limitations (explicitly NOT resolved)
| # | Limitation | Consequence | Current control |
|---|---|---|---|
| L1 | **No host-loss recovery.** If Thor, Proxmox or the network fails while Remote EMS is on, the plant may stay in mode 3 or 0 with the setpoint active. | Uncontrolled grid charge, or discharge until plant/BMS limits. Worst-case behaviour hasn't been characterised (see R2). | Attended operation only; MySigen manual control; 30 s bound. **Main blocker to anything longer.** |
| L2 | **Writer exclusion is cooperative only.** The flock and panel isolation cover controller.py, the RC28 child and the RC29 closure tool. Legacy entry points and other hosts aren't excluded. | A second writer could conflict. | Operator discipline; known legacy paths are disabled in code (e.g. the direct charge CLI). Not proven system-wide. |
| L3 | **No battery-attributable grid-side energy measurement.** | Delivered kWh per slot is unknown, so commitment accounting stays `HOLD_UNMETERED_DELIVERY`. | No energy claims made. |
| L4 | **Export setpoint is inverter-side.** | A fixed 650 W doesn't give 650 W export; with household load ≥ 650 W, export is zero. Any trading logic must model this. | Documented (E3). |
| L5 | **Operator abort (Ctrl-C) leaves an unclosable latch.** The child still hands back, but the parent writes no `SESSION_RESULT`, so RC29b review rejects the trace. | Fails closed; further pilots blocked until a reviewed code extension. | Procedure says intervene in MySigen, not Ctrl-C. |
| L6 | **Phase-label race** at the DURING/AFTER boundary in the RC27 observer. | Can make a review fail closed; no unsafe effect. | Documented. |
| L7 | **Evidence is hash-verified, not immutable.** Root can alter traces and closure records. | Tampering is detectable only between review and close. | Audit retained; no stronger guarantee claimed. |
| L8 | **Child delegate timeout is 85 s.** Worst-case systemctl delays (3 × 20 s) plus 30 s could exceed it, triggering SIGINT handback and `HOLD_RECOVERY_REQUIRED`. | Fails closed. | Not seen in practice. |
| L9 | **Live Thor source isn't in the repository.** The Octopus sync, advisory planner, nightly optimiser and any on-host edits are missing. | Pricing logic hasn't been reviewed; the repo isn't yet the source of truth. | Collection script exists; not yet run. |
| L10 | **Only one sample of each pilot**, at about 66 % SOC, low household load and a single firmware version. | Behaviour at other SOC, temperature or load levels isn't characterised. | No generalisation claimed. |

## 5. Operational restrictions in force from closeout
1. **No live Modbus writes without explicit operator approval for the specific session.** Earlier approvals never carry over.
2. **Only the two commissioned actions:** GRID_CHARGE 500 W/30 s and EXPORT 650 W/30 s, attended, via RC28 `--execute ... --operator-ack` from the `phase3b-supervised-rc29` tree.
3. **No longer durations, other setpoints, timers, schedules or unattended execution.** Full-slot paths stay blocked.
4. **RC13 frozen;** its output stays research/advisory and is **not** execution permission. Autonomous dispatch is disabled.
5. **Never write 40034.**
6. **Never delete a recovery latch by hand.** Clear it only with the RC29b `--review`/`--close` procedure, or automatically on clean evidence.
7. **Keep MySigen available on a device that doesn't depend on Thor** during any live action. Intervene in MySigen, not with Ctrl-C.
8. **Retain all session traces, audit JSONL and `rc29-latch-closures/` records.**

## 6. Closure statement
Both functions are accepted as working and safely handed back under attended 30-second conditions:
- **Charge:** grid charging at 500 W.
- **Export:** battery discharge at 650 W on the inverter side.

The recovery-latch design has been shown to work under a real fault (E1–E2). Phase 3B functional commissioning is therefore closed. Every limitation in §4 carries forward into the next phase, and the restrictions in §5 stay in force until changed by explicit, reviewed operator decision.
