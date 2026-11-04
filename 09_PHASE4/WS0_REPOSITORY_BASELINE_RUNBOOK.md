# WS0: Repository baseline and live-source capture (runbook)

**Status:** proposed; runs once Phase 4 gate G0 is approved. **No Modbus, no service changes, no secrets leave Thor.**
**Goal:** make the repository match what actually runs on Thor, and produce the **writer inventory** needed for L2.

## Gaps in the existing collector (`06_THOR_COLLECTION/collect_thor_source_readonly.sh`)
| Gap | Consequence | Addressed by |
|---|---|---|
| Collects only `.py .ps1 .sh .md` | Misses systemd units and timers, nginx and web templates (`.html/.js/.css`), non-secret JSON config | Step 2 |
| Filters secrets **by filename only** | A key embedded inside a `.py` or `.ps1` would be collected, and the repo is **public** | Step 3 (content scan) |
| No writer inventory | System-wide writer exclusion can't be assessed | Step 4 |

## Steps (operator, on Thor, read-only)
**1. Source snapshot (existing script, unchanged):**
Copy `06_THOR_COLLECTION/collect_thor_source_readonly.sh` from the repo into `/tmp/copy-paste/` first, then:
```bash
clear
sudo bash /tmp/copy-paste/collect_thor_source_readonly.sh
```

**2. Deployment state (names and configs only, no data):**
```bash
clear
D=/tmp/copy-paste/thor-deploy-$(date -u +%Y%m%dT%H%M%SZ); mkdir -p "$D"
systemctl list-units --all --no-pager 'sigen*' > "$D/units.txt"
systemctl list-timers --all --no-pager > "$D/timers.txt"
for u in $(systemctl list-unit-files --no-legend 'sigen*' | awk '{print $1}'); do systemctl cat "$u" > "$D/$u.txt" 2>&1; done
sudo find /opt/sigenstor/scripts -type f \( -name '*.html' -o -name '*.js' -o -name '*.css' \) -print0 | sudo tar --null -czf "$D/web.tgz" -T - 2>/dev/null || true
sudo find /opt/sigenstor -maxdepth 3 -type f -name '*.json' -size -64k -printf '%p %s %TY-%Tm-%Td\n' > "$D/json_inventory.txt"
crontab -l > "$D/crontab_user.txt" 2>&1; sudo crontab -l > "$D/crontab_root.txt" 2>&1
python3 --version > "$D/runtime.txt"; pwsh --version >> "$D/runtime.txt" 2>&1 || true
ls "$D"
```
JSON *contents* are deliberately not copied. Only an inventory is taken; non-secret configs are added by hand after review.

**3. Secret content scan (must be clean before anything is committed):**
```bash
clear
cd /tmp/copy-paste && mkdir -p scan && tar -xzf SigenStor_Thor_Source_*.tar.gz -C scan
grep -rnIE "sk_live_[A-Za-z0-9]+|api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9_]{8,}|Authorization:|Basic [A-Za-z0-9+/=]{12,}|password\s*[:=]\s*['\"][^'\"]+|[0-9]{13}\b|A-[0-9A-F]{8}\b" scan || echo NO_SECRET_PATTERNS
```
The patterns cover Octopus keys, auth headers, 13-digit MPANs and `A-XXXXXXXX` account IDs. Expect false positives from the 13-digit pattern (e.g. millisecond timestamps); check each hit by eye. **Any hit:** remove it from the snapshot, move the value to a root-only config file, and rotate the key if it was ever in a public commit.

**4. Writer inventory (read-only grep over all code):**
```bash
clear
cd /tmp/copy-paste/scan
grep -rnIE "write_register|write_registers|write_u32|\.write\(4003|\.write\(4002|call\(\s*(6|16)\s*,|FC ?(06|16)|Invoke-.*Modbus|WriteSingleRegister|WriteMultipleRegisters" . > ../writer_inventory.txt; wc -l ../writer_inventory.txt
grep -rnIE "192\.168\.0\.8|:502\b|unit\s*=?\s*247" . > ../plant_address_refs.txt; wc -l ../plant_address_refs.txt
```
For each hit, record: file, entry point (CLI, service or timer), whether it takes `/run/lock/sigen-rtm-v12-commission.lock`, whether it checks the RC21 latch, and whether it's reachable from a running unit or timer.

**5. Commit (via the reviewed PR route):** `08_THOR_LIVE_SOURCE/` (source, web assets, unit files, timers), `08_THOR_LIVE_SOURCE/WRITER_INVENTORY.md` (the table from step 4) and `DEPLOYMENT_MANIFEST.md`. Add a pre-commit secret scan (e.g. `gitleaks`). Because the repo is public, run it over the **whole history** once.

## G0 exit criteria
- [ ] The repo source matches Thor (`diff -r` against `/opt/sigenstor/scripts`, ignoring `__pycache__`). Differences are explained.
- [ ] The Octopus sync, advisory planner, nightly optimiser and RC13 producer are located and committed.
- [ ] The writer inventory is complete; each writer is classified as guarded (lock + latch) / disabled / **unguarded**, and unguarded ones go into WS2.5.
- [ ] Secret scan clean over the snapshot and the full repo history.
