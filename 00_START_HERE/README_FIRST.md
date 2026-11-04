# SigenStor / Octopus Agile — Full Claude Handover (4 November 2026)

**Recommended starting point:** `00_START_HERE/CLAUDE_AGENT_BRIEF.md`, then `PROJECT_STATUS_AND_LIVE_INCIDENT.md` and `ARCHITECTURE_AND_INTERFACES.md`. The **current, latest source and test suite** is in `01_CURRENT_RC28/`; original release ZIPs RC1–RC28 are intact in `02_RELEASE_ARCHIVE/` for reproducibility and source-lineage review. `04_BUILD_PROVENANCE/` contains build generators from the session; these are **development tooling, not production code**.

## Exactly what this export does and does not include

Includes all **28 RC1–RC28 release ZIPs found in this conversation's working directory**, the extracted RC28 tree (without incidental `__pycache__`), three earlier source/snapshot tarballs, available build scripts and test logs, two planning Word documents, and a handover authored from the latest operator outputs. The user supplied the latest commissioning evidence as pasted text, which is transcribed in the handover. The **actual Thor runtime log and full live trace are NOT available to this export**. No credentials or live Octopus secret files are intentionally included.

`06_THOR_COLLECTION/collect_thor_source_readonly.sh` helps the operator collect a fresh **source-only** snapshot from Thor, without network writes or touching inverter state. Live readings, dynamic telemetry DB, secrets, certificates, protected configuration and the physical device are **not in this archive**. All source snapshots are point-in-time copies and may be stale.

## Handover warnings

- Latest RC28 has executed one **real, operator-authorised 30-second 500W GRID_CHARGE pilot**. It demonstrated command response and verified handback. **The commissioning recovery latch is still SET**. Do not start another session or delete/reset the latch based solely on this archive.
- `HOLD_RECOVERY_REQUIRED` arose because one invalid derived `home_kw` sample in the AFTER phase made the RC27 evidence-quality gate fail despite verified handback. A safe latch-clearance workflow is **not yet commissioned**; the status is deliberately unresolved.
- Export at 650W has not yet been commissioned in this integration. Physical battery-attributable grid-side energy has not been formally accepted. Full-slot and autonomous dispatch are NOT approved.
- No independent host-loss recovery was commissioned. A separate Linux recovery supervisor prototype was explored but **explicitly rejected** by the user; its archived prototype is **deprecated** and is not part of the target design.
- The user has a former developer / EMS-BMS controls engineering background, wants assistant-led engineering, minimal prompting, substantive progress and no needless regression proliferation.

## Original file integrity

`MANIFEST_SHA256.txt` lists hashes for all handover files. Historical release ZIPs are preserved byte-for-byte. Release-internal SHA256SUMS files also exist; review them before deploying. No file is automatically installed by unpacking this handover.
