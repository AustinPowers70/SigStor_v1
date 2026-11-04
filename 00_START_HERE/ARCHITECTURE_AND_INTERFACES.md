# Architecture, registers, conventions and installation

## Hosts and file layout

- Proxmox VE node: `thor`. Ubuntu 26.04.1 unprivileged LXC at `192.168.0.251`; web dashboard `http://192.168.0.251:8088` with nginx auth; timezone Europe/London.
- Production source: `/opt/sigenstor/scripts/`; runtime data `/opt/sigenstor/data/`; logs `/opt/sigenstor/logs/`. Update staging exclusively `/tmp/copy-paste/` (not bare /tmp). Shell code blocks must begin with `clear`.
- Latest installed target: `/opt/sigenstor/scripts/phase3b-supervised-rc28/` (latest on-host `--check` returned READONLY_ELIGIBLE, live 30s GRID_CHARGE later performed). The original phase1 controls are in `/opt/sigenstor/scripts/phase1-supervised/`. Runtime scripts and services may differ from this snapshot; collect/compare first.
- Planner 5-minute systemd timer (advisory only), 5-minute telemetry, hourly Octopus sync, nightly shadow optimisation. Do not change their running modes without reviewing deployment state.

## SigenStor Modbus TCP (previously commissioned)

| Function | Protocol address / holding reg | Meaning |
|---|---|---|
| FC04 input block | start 30005, length 34 | read SOC, grid, battery, PV; decoder in `power_acquisition_rc9.py` |
| Remote EMS | 40029 | 0 OFF / 1 ON |
| Operating/PCS mode | 40031 | 2 self-consumption, 3 grid charge, 0 PCS for export pilot |
| Charge limit | 40032 | U32 power setpoint; commissioned 500 W |
| PCS export request | 40001 | signed U32 request; commissioned 650 W; handback 0 |
| Discharge limit | **40034** | **never write**; remains unchanged (0xFFFFFFFF historically) |

- Unit ID 247, TCP port 502. Plant EC8 SP, firmware historically V100R001C22SPC117, battery 18 kWh, import/export limit historically 8 kW, no PV.
- Battery sign: +charge / -discharge. Grid sign: +import / -export. Conversion of battery power to aggregate grid flow is **not** a trivial one-to-one relationship because household load changes. No energy-attribution claim without correlated trace and metering evidence.
- Handback target: PCS request 0, operating mode 2, Remote EMS 0, verify readback; charge pilot sequence and export pilot sequence in `supervised_charge.py` and `supervised_export.py`. Original live `controller.py` and RC28 wrapper may invoke those routines. Review exact register writes and error paths before reusing.

## Controller and qualification architecture

- Octopus Agile import product `AGILE-24-10-01`, outgoing export `AGILE-OUTGOING-19-05-13`; account-specific tariff suffix `-J` historically. Never include API keys in an AI handover.
- `RC13`: frozen economic optimiser, research/advisory output `/opt/sigenstor/data/rtm/v12-demand-backed-qualified-rc13.json`, source freshness typically 600 seconds.
- `R5`: verified envelope `/opt/sigenstor/data/rtm/phase3a-verified-envelope-r5.json`; contract `GRID_SIDE_CHARGE_AND_EXPORT_KWH`, research-only flags, zero Modbus writes.
- `R6`: slot setpoint accounting. `RC13` trading decisions do **not** constitute execution permission.
- `RC27`: wrapper attempts 2s physical telemetry before/during/after around legacy live controller, with durable recovery latch, TTY challenge, verified postflight and panel recovery.
- `RC28`: distinct manual-only 30-second commissioning eligibility, no tariff slot required; `--check GRID_CHARGE|EXPORT` is nonactuating, `--execute ... --operator-ack` is live when separately authorised. RC28 delegates to `commissioning_controller_rc28.py` behind a one-shot file descriptor; review this boundary and environment restrictions.
- Local controller lock historically `/run/lock/sigen-rtm-v12-commission.lock`; systemd authority panel `sigen-rtm-authority-panel.service`. Stopping/restarting authority panel and verifying before/after are part of single-writer assumptions, but legacy entrypoints exist, so **system-wide writer exclusion has not been proven**.
- RC21 persistent recovery-required latch and RC22 attestation contract; uncommissioned independent witness must not be treated as physical proof.

## Safety and scope

- Manual attended 30-second commissioning only: 500 W grid charge, 650 W PCS export, explicit per-action operator approval via MySigen supervision and local typed prompt.
- NO autonomous dispatch or unattended scheduling, NO 40034 write, NO full-slot actuation approval.
- Host/Proxmox/network loss during remote EMS actuation can prevent auto-handback. The user **does not want** a separate Linux recovery supervisor; the residual hazard has not disappeared. Don't silently remove the safeguard or imply the accepted operating envelope is wider than it is.
- Past NAS incident affected Proxmox host; do not conflate host reliability with tested plant-independent recovery.

## Suggested code reading order

1. `controller/attended_commissioning_rc28.py`, `controller/commissioning_permit_rc28.py`, `controller/commissioning_controller_rc28.py`
2. `controller/attended_commissioning_rc27.py`, `controller/recovery_latch_rc21.py`
3. `controller/controller.py`, `controller/supervised_charge.py`, `controller/supervised_export.py`
4. `controller/commissioning_preflight_rc18.py`, `controller/power_acquisition_rc9.py`, `controller/commissioning_capture_rc26.py`
5. `controller/rc13_gateway.py`, `controller/slot_commitment.py`, `controller/commissioning_handoff_rc19.py`
6. `accepted/phase3a/*` plus `accepted/phase2-supervised/*` and tests.

This is a handover of engineering source, **not** a claim the full production installation was replicated.
