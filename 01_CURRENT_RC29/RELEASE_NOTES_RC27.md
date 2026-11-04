# RC27 — Attended physical-pilot correlation

- Adds real-world operator-gated orchestration around the existing commissioned controller; no new register writes/values.
- Captures physical FC04 telemetry pre/during/post action with a durable recovery latch.
- Fails closed on any uncertain controller exit, telemetry integrity, panel restoration or physical handback.
- Explicit local TTY consent required for each potential live actuation.
- Does not solve Thor/LXC/network loss recovery and does not authorise unattended/full-slot dispatch.
- RC26 read-only capture, RC25 evidence tools and RC13 optimiser unchanged.
