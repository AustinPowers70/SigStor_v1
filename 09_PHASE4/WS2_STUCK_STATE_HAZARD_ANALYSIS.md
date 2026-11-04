# WS2: Stuck-state hazard analysis and recovery options (worksheet)

**Status:** offline analysis for review. Facts marked **[E]** come from accepted evidence (E1–E3). Facts marked **[U]** are unknown and must be established. Nothing here is authorised.
**Question:** if Thor, Proxmox or the network is lost (or the operator presses Ctrl-C) while Remote EMS is ON, what does the plant do, for how long, and what does it cost? The answer sets the **maximum tolerable exposure**, which caps WS3.

## 1. Commissioned states that could get stuck
| State | Registers left set | Physical behaviour [E] |
|---|---|---|
| S-CHG | 40029=1, 40031=3, 40032=500 | Grid charges the battery at about 0.5 kW. Household load is supplied from the grid. |
| S-EXP | 40029=1, 40031=0, 40001=650 | Inverter discharges about 0.65 kW; net grid export = 0.65 − household load. |

## 2. Worst-case consequences (to be filled in from WS2.1–2.3)
| Item | S-CHG | S-EXP |
|---|---|---|
| Does the plant revert by itself after Modbus silence? | **[U]** (WS2.1) | **[U]** (WS2.1) |
| Where does it stop by itself? | Battery full (100 % or BMS charge cutoff) **[U] exact behaviour** | Discharge cutoff / backup SOC set in MySigen **[U] value**. 40034 is never written, so the plant/BMS limits apply. |
| Time to reach that stop, from SOC 66 % (18 kWh) | about 34 % × 18 kWh ≈ 6.1 kWh ÷ 0.5 kW ≈ **12 h** of grid charging | at 0.65 kW: (66 % − cutoff) × 18 kWh ÷ 0.65 kW. E.g. a 10 % cutoff gives ≈ 10.1 kWh ÷ 0.65 ≈ **15.5 h** |
| Energy and cost exposure | ≤ about 6.1 kWh of charging at the prevailing Agile import rates (adverse if peak-rate) plus household load as normal | Stored energy sold at the export rate rather than used; loss of reserve for the house (**the more serious one**: the house is left unsupported at night or in an outage) |
| Equipment risk | Low (within ratings) **[U] thermal at long duration** | Low (within ratings) |
| Detection (once WS1 is in) | M1/M2 within about 20 s if Thor is up; M8 within about 3 min if Thor is down | same |
| Human recovery time | MySigen override **[U] measured time** (WS2.3) | same |

**Exposure at higher power (relevant to WS3):** with export at P kW, time to cutoff scales as 1/P. At 2 kW from 66 % with a 10 % cutoff, it's about 5 h. Reserve loss is the dominant hazard. A **stuck export** therefore needs a recovery path faster than the time it takes to drain the reserve the household needs. A stuck charge is mainly a cost hazard.

## 3. Recovery options (without an independent Linux recovery host, which was rejected)
| Option | Covers | Status / next step |
|---|---|---|
| R1 Inverter-native communication-loss fallback | Thor, network and process loss | **[U]** Ask Sigenergy (draft below). If it exists, plan an attended drill: start a 30 s pilot, block Thor→inverter traffic and observe the revert. |
| R2 MySigen manual override | Any loss, if the operator is reachable | **[U] time to recover.** Attended drill during an approved pilot: take control in MySigen and measure the time to self-consumption. |
| R3 WS1 alerting (M1/M8) | Detection only | Designed (WS1). Turns "unknown duration" into "time to alert + R2". |
| R4 Operator-abort fix (L5) | Ctrl-C mid-pulse | Code: the parent records `OPERATOR_ABORT` / `DELEGATE_EXIT` / `SESSION_RESULT` after the child's handback; extend RC29b to accept only with fresh verified handback. Needs tests and independent review. |
| R5 Writer exclusion (L2) | A second writer causing a conflicting state | From the WS0 inventory. |
| R6 Thor resilience (systemd watchdog, UPS, LXC auto-start) | Process crash, brief power loss | Reduces probability; **doesn't** cover host or network loss. |
| R7 Exposure limits in the envelope (WS3) | All | Cap duration × power so that **worst stuck exposure before alert + human recovery** stays within an accepted bound. |

## 4. Proposed acceptance rule for WS3 (for decision)
A WS3 step (duration D, power P) is eligible only if:
1. R3 is live (G1 passed), **and**
2. either R1 is demonstrated, **or** R2 has been drilled and measured with time T_recover, **and**
3. for export: the reserve remaining after (time to alert + T_recover + D) at P stays ≥ the household reserve requirement. For charge: the cost of that period at the worst Agile import price over the past 30 days is ≤ an operator-set limit.

## 5. Draft question to Sigenergy support (for the operator to send)
> We operate a SigenStor EC 8 SP (firmware V100R001C22SPC117, to be confirmed) using the Modbus TCP Remote EMS interface (40029 Remote EMS enable, 40031 control mode, 40001 active-power target, 40032 charge limit).
> 1. If the Modbus TCP client disconnects or stops communicating while Remote EMS (40029=1) is enabled, does the inverter keep the last command indefinitely, or is there a communication-loss timeout that reverts to the local EMS mode (e.g. maximum self-consumption)?
> 2. If a timeout exists, which register configures it, what are its range and default, and what state does it revert to?
> 3. Is a periodic heartbeat/keep-alive register required or available for Remote EMS?
> 4. In PCS remote control mode (40031=0) with a positive 40001 target, which battery SOC limit stops discharge when register 40034 is left at its default? Is it the backup/discharge cutoff SOC set in the MySigen app?
> 5. Can the MySigen app override or disable Remote EMS while a Modbus client has it enabled, and is that override immediate?

## 6. Facts established so far (inputs)
- [E] Mode-3 charge at 40032=500 gives about +0.5 kW battery; household load moves to the grid (E1).
- [E] Mode-0 with 40001=650 gives about −0.65 kW battery at the inverter side; net export = 0.65 − load (E3).
- [E] The handback sequence works physically in both modes (E1, E3).
- [U] Everything marked [U] above. **Don't assume** a communication-loss revert exists until Sigenergy confirms it or a drill shows it.
