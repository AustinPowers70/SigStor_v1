# Items unavailable in this conversation export / obtain from Thor

The following could not be retrieved from the live Thor host (no direct access). They are **not included** and must not be fabricated:

1. Latest complete `/opt/sigenstor/scripts` tree, including advisory scheduler, historical optimiser and **any edits done directly on host**; release ZIPs cover a substantial portion but not necessarily the entire production tree.
2. Full raw `/opt/sigenstor/data/rtm/rc27-pilot-8d39f77fc0e244b69f79f0257b56ba07.jsonl`; only summary and exceptional sample supplied by operator. Also current RC28 latch file, after this handover.
3. Complete telemetry SQLite DB, actual Octopus meter consumption/export history, inverter register dumps at time of trial, contemporaneous MySigen screenshot and detailed daemon journal.
4. Exact live `systemctl` status/overrides, Python/PowerShell installs, permissions, watchdog settings and real host/network topology after recent NAS issue.
5. Any Octopus API keys, account IDs, meter identifiers or auth passwords — intentionally excluded, must remain secret and local.
6. Any application files that were discussed in older chats but not present in `/mnt/data` source/release archives.

The optional collector script in `06_THOR_COLLECTION/` collects **source code only** and creates a separate archive on the user's Thor host. Keep telemetry/credentials separate, inspect them manually, and avoid uploading secrets to an LLM. If the operator provides the session trace, confirm it has no sensitive household metadata before sharing.
