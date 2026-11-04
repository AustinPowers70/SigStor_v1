# SigenStor commissioning evidence record

Plant: Sigenergy SigenStor EC 8 SP, 18 kWh (2 × BAT10), no PV. Host: Thor LXC 192.168.0.251. Inverter: 192.168.0.8:502, unit 247.
Conventions: battery +charge/−discharge; grid +import/−export.

Standing scope:
- RC13 frozen; autonomous dispatch disabled; register 40034 never written.
- Operator-attended 30 s pilots only.
- No host-loss recovery: loss of Thor, Proxmox or the network during a pulse can prevent automatic handback.

---

## E1: GRID_CHARGE 500 W / 30 s pilot (ACCEPTED, with stated limits)

| Item | Value |
|---|---|
| Session | `8d39f77fc0e244b69f79f0257b56ba07` |
| Time | 2026-11-04, latch armed 18:49:03.110Z |
| Entry point | RC28 `attended_commissioning_rc28.py --execute GRID_CHARGE --operator-ack` (TTY challenge) |
| Command sequence | 40032=500 (U32), 40031=3, 40029=1; handback 40031=2, 40029=0 with readback |
| Controller exit | 0; no delegate timeout; observer error none; observer Modbus writes 0 |
| Coverage (valid) | BEFORE 3 / DURING 16 / AFTER 3; 1 invalid AFTER sample |
| Invalid sample | 2026-11-04T18:49:41.123968Z `SampleError: invalid power sample: home_kw:implausible` (derived load plausibility) |
| Plant handback | Verified post-session (Remote EMS 0, mode 2, PCS 0); authority panel restored |
| Operator observation | MySigen showed expected charge; "worked as expected" |
| Original RC27 status | `HOLD_RECOVERY_REQUIRED` (evidence-quality defect coupled to recovery state) |

Valid-sample summary (operator-generated):

| Phase | n | Mean battery kW | Range | Mean grid kW | Range | SOC |
|---|---:|---:|---|---:|---|---|
| BEFORE | 3 | −2.391 | −3.525…−0.916 | −0.470 | −1.420…+0.009 | 66.2 % |
| DURING | 16 | +0.351 | −0.701…+0.508 | +1.929 | +0.009…+2.495 | 66.2 % |
| AFTER | 3 | −3.119 | −3.517…−2.515 | +0.043 | −0.019…+0.134 | 66.2 % |

**Accepted:**
- **Command response:** the battery moved from serving household load (discharging) to charging, peaking at +0.508 kW, in line with the 500 W setpoint. Grid import rose by about the household load plus the charge.
- **Control and handback:** verified handback, panel restoration and single-writer locking for a cooperating entry point.

**Not accepted / unverified:**
- Battery-attributable grid-side energy (nominal 4.17 Wh is not an observed total).
- Host-loss recovery.
- System-wide writer exclusion.
- Full-slot operation.

---

## E2: Recovery-latch closure for E1 (ACCEPTED)

| Item | Value |
|---|---|
| Tool | RC29b `latch_closure_rc29.py` (`--review`, then `--close --operator-ack`); independently reviewed (ChatGPT), 394/394 offline tests passed independently |
| Session | `8d39f77fc0e244b69f79f0257b56ba07` |
| Closure time | 2026-11-04 20:09:39Z |
| Status | `LATCH_CLEARED_OPERATOR_WITNESSED` |
| Evidence review | Lifecycle complete and in order; exit and handback cross-checks consistent; one AFTER `home_kw:implausible` sample accepted as **degraded telemetry** (allowlisted, not during actuation) |
| Plant recovery | 3 fresh read-only readbacks: Remote EMS OFF, mode 2 self-consumption, PCS demand 0; authority panel active |
| Ownership | Exclusive controller lock held from before the final readbacks until after latch removal |
| Modbus writes during clearance | 0 |
| Audit | Write-once records in `/opt/sigenstor/data/rtm/rc29-latch-closures/` (review, closure-authorised, cleared). Hash-verified, not immutable. **Retain.** |

Closure does **not** authorise further pilots. Host-loss recovery and battery-attributable grid-side delivery remain unverified.

---

## E3: EXPORT 650 W / 30 s pilot (ACCEPTED: direction and command response)

| Item | Value |
|---|---|
| Session | `deff25df597a435a9f4d589e60a9b7f4` |
| Date | 2026-11-04 |
| Entry point | RC28 `attended_commissioning_rc28.py --execute EXPORT --operator-ack` from the installed `phase3b-supervised-rc29` tree (RC29b verdict) |
| Command sequence | 40029=1, 40031=0 (PCS remote control), 40001=650 (U32); handback 40001=0, 40031=2, 40029=0 with readback |
| Controller exit | 0; complete lifecycle; full telemetry coverage |
| Invalid samples | **0** |
| Plant handback | Verified by the controller and by the independent post-preflight: Remote EMS OFF, PCS demand 0, self-consumption; authority panel restored |
| Recovery latch | **Cleared automatically** (`SUPERVISED_PILOT_HANDBACK_CONFIRMED`; no RC29b closure needed) |
| Independent review | Passed (ChatGPT), before and after execution |

Phase means (valid samples):

| Phase | Battery kW | Grid kW | Household kW (derived) |
|---|---:|---:|---:|
| BEFORE | −0.512 | −0.003 | ≈0.51 |
| DURING | −0.669 | −0.154 | 0.515 |
| AFTER | −0.447 | +0.023 | ≈0.47 |

Consistency check: household = grid − battery = −0.154 + 0.669 = 0.515 kW ✓.

**Register-semantics finding (pre-declared hypotheses):**
- **H1 (inverter/PCS output = 650 W): CONSISTENT.** DURING battery −0.669 kW, within 0.019 kW of −0.65.
- **H2 (grid connection point = 650 W export): NOT consistent.** Net grid export averaged about 0.154 kW.
- **Conclusion:** `40001=650` commands about 650 W of inverter/battery discharge. Net grid export is about 650 W minus household load.
- **Sign:** positive 40001 means discharge/export direction (**accepted**).

**Accepted:**
- Export direction and command response.
- 40001 sign and scaling (raw W at the inverter).
- Verified handback and panel restoration.
- The automatic latch path on clean evidence.

**Not accepted / unverified:**
- Battery-attributable grid-side energy (net about 0.154 kW × 30 s ≈ 1.3 Wh is a telemetry estimate, not metered).
- Host-loss recovery.
- System-wide writer exclusion.
- Any duration other than 30 s, any other power level, and unattended use.
