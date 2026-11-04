# Project state and last physical commissioning run

**Date:** 2026-11-04 (Europe/London, GMT). **Host:** `thor`, Proxmox unprivileged Ubuntu LXC `192.168.0.251`. **Plant:** Sigenergy SigenStor EC 8 SP, 18 kWh (2 × BAT10), no PV. **Inverter Modbus:** `192.168.0.8:502`, unit 247. This address is private LAN and a historical value, verify on site.

## Accepted development status

- Phase 3A offline integration **accepted/closed 31 Oct 2026**, while physical full-duration commissioning was deferred.
- Economic optimiser RC13 frozen unchanged; verified R5 grid-side kWh contract; R6 setpoints and R9/R10 energy adapters. System remains **no autonomous dispatch**.
- RC22 accepted on Thor with 277/277 offline tests; RC23 297/297; RC24 302/302; RC25 314/314; RC26 targeted 5/5; RC27 targeted 10/10; RC28 targeted 22/22 during package construction (12 new RC28 plus prior RC27). Repeated offline test counts are **not evidence of live actuation acceptance**.
- RC26 physical read-only baseline at `2026-11-04T18:25:33Z`: SOC 69.9%, Remote EMS off, self-consumption, PCS zero. 38 valid samples, 0 invalid; 74.01 s integrated with largest gap 2.001s, battery-port signed -46.218Wh, aggregate-grid signed +0.029Wh. RC26 report does **not** establish grid-side battery-attributable energy.
- RC27 economic-qualified check failed with HOLD_OUTSIDE_HORIZON. RC28 introduced distinct **manual commissioning only** qualification; read-only check returned READONLY_ELIGIBLE (no RC13 slot needed). This does not change the trading optimiser.

## First real physical commissioning pilot (4 Nov 2026 ~18:49Z)

Operator explicitly approved one **500 W, 30-second GRID_CHARGE** trial, viewed MySigen, and reported it 'worked as expected'. RC28 delegated to existing commissioned live controls with 2-second RC27 observer running. Summary:

```json
{"action":"GRID_CHARGE","autonomous_dispatch":false,"controller_invoked":true,"coverage":{"AFTER":3,"BEFORE":3,"DURING":16},"delegate_timeout":false,"host_loss_recovery_verified":false,"invalid_samples":1,"live_controller_exit":0,"modbus_writes_by_observer":0,"observer_error":null,"panel_restored":true,"physical_delivery_verified":false,"plant_handback_verified":true,"recovery_latch_retained":true,"schema":"SIGEN_PHASE3B_RC27_ATTENDED_PILOT_CORRELATION","session_id":"8d39f77fc0e244b69f79f0257b56ba07","status":"HOLD_RECOVERY_REQUIRED","trace_file":"/opt/sigenstor/data/rtm/rc27-pilot-8d39f77fc0e244b69f79f0257b56ba07.jsonl"}
```

Operator-generated evidence summary, **valid telemetry only**:

| Phase | n | Mean battery kW | Battery range kW | Mean grid kW | Grid range kW | SOC |
|---|---:|---:|---|---:|---|---|
| BEFORE | 3 | -2.391 | -3.525 to -0.916 | -0.470 | -1.420 to +0.009 | 66.2% |
| DURING | 16 | +0.351 | -0.701 to +0.508 | +1.929 | +0.009 to +2.495 | 66.2% |
| AFTER | 3 | -3.119 | -3.517 to -2.515 | +0.043 | -0.019 to +0.134 | 66.2% |

**Convention:** battery +charging / -discharging; grid +import / -export. Positive peak battery +0.508 kW agrees qualitatively with commanded 500 W setpoint; grid import response is evident. The 30s at 500 W corresponds to about 4.17Wh at nominal setpoint (not an observed energy total). Different household states in BEFORE and AFTER mean attribution requires care. SOC unchanged at 66.2% is expected at this brief duration.

**Invalid sample:** exactly one AFTER sample at `2026-11-04T18:49:41.123968+00:00`: `SampleError: invalid power sample: home_kw:implausible`. This is a derived household-load plausibility failure, not by itself proof of failed plant handback.

**Persistent latch record (operator read-only inspection):**

```json
{"armed_utc":"2026-11-04T18:49:03.110378+00:00","schema":"SIGEN_RC21_RECOVERY_LATCH","session_id":"8d39f77fc0e244b69f79f0257b56ba07","state":"RECOVERY_REQUIRED_UNTIL_VERIFIED"}
```

Path from session: `/opt/sigenstor/data/rtm/rc28-recovery-required.json`. Current latch state is **not freshly queried since user output**. Do not assume cleared. User's most recent message stated a handover to Claude; no additional live actions were approved.

## Precise identified software issue

In `01_CURRENT_RC28/controller/attended_commissioning_rc27.py` (called by RC28 wrapper), the `pass_evidence` predicate requires `observer.invalid == 0` in addition to exit code 0, plant handback, panel restoration, and sample counts. A single invalid AFTER `home_kw` observation therefore retains the persistent **recovery** latch despite successful independently checked handback. Evidence completeness and plant recovery state are incorrectly coupled. This should be redesigned carefully, **not bypassed**. The existing `RecoveryLatch` must not be manually deleted or forcibly cleared without fresh plant verification and explicit operator-authorised recovery procedure.

## Current disposition

- Functional charge command response: **demonstrated**.
- Verified state reported after session: Remote EMS off, PCS zero, self-consumption and authority panel restored.
- Telemetry: 22 valid samples, one invalid AFTER.
- Physical battery-attributable grid-side energy: **not formally verified**.
- Recovery latch: **RETAINED / unresolved**.
- Export pilot: **not yet approved / executed**.
- Full-duration and unattended operation: **not authorised**; loss of Thor/Proxmox/network can prevent automatic handback.

Immediate next work is code review, safe separation of evidence-quality flags from physical recovery state, and a supervised read-only re-verification / operator-authorised latch recovery procedure. Do **not** incrementally generate another chain of R... test-only packages unless a specific defect warrants it. Then seek explicit fresh approval for the export pilot only when safe to do so.
