# WS2: Stuck-state hazard analysis and recovery options (worksheet)

**Status:** Offline analysis for review; no operations authorised. Evidence labels: **[E]** established by the 30-second charge/export pilots; **[U]** still unknown.

## Stuck control states
- S-CHG: 40029=1, 40031=3, 40032=500; observed grid charge near 0.5 kW.
- S-EXP: 40029=1, 40031=0, 40001=650; observed inverter-side battery discharge near 0.65 kW, with grid export equal to discharge minus household load.

## Risks
- [U] No verified inverter-native Modbus silence timeout or reversion to self-consumption.
- [U] Actual MySigen manual override time with Remote EMS active.
- [U] Actual BMS stopping SOC and persistent-command consequences, especially reserve depletion in export mode.
- An extended command at higher power increases exposure if Thor, Proxmox, or the network fails. A host-local watchdog does not protect against complete host failure.
- Writer exclusion remains cooperative only; inventory of other Modbus writers is not complete.

## Recovery workstream options
1. R1: Ask Sigenergy whether a Remote EMS communication-loss watchdog or revert-to-self-consumption timeout exists; don't assume.
2. R2: Operator-approved drill to measure manual MySigen override time.
3. R3: Off-Thor dead-man monitoring and read-only local state alerts; detection alone is not recovery.
4. R4: Improve Ctrl-C handling to record a complete audit after child handback, keeping latch fail-closed until verification.
5. R5: Inventory, disable or guard all legacy writers.
6. R6: Improve Thor resilience (UPS, watchdog, auto-start), without claiming this covers host/network loss.
7. R7: Set a maximum allowed duration and power using the measured alert-and-recovery envelope.

## WS3 eligibility proposal
No longer session should be commissioned until G1 monitoring is accepted, an inverter-native or observed manual recovery path is characterised, the exposure limits preserve household reserve, and all writers are inventoried.

## Questions for Sigenergy
1. Does Remote EMS (40029=1) persist after Modbus silence, or revert automatically?
2. What register, timeout, or heartbeat configures any fallback?
3. In PCS mode 40031=0, what discharge/backup SOC protects the battery when 40034 is unchanged?
4. Can MySigen override Remote EMS promptly, and what state is restored?

This is a preparatory summary of Claude's WS2 worksheet; the original full source remains in the uploaded runbook bundle. It does not authorise live operations or autonomous dispatch.