# RC24 — Authority isolation transaction hardening

RC23 verified on Thor (297/297). RC24 moves the durable recovery latch to BEFORE the authority-panel stop attempt and marks isolation as potentially changed before invoking stop. Partial stop failure now enters the attempted-restoration path; the latch persists after any abort, including a restored panel, pending controlled inspection. No inverter writes, no live CLI, no added services, no independent host-loss recovery claim. RC13, 40034 and all charge/export limits remain unchanged.

Scope: 5 targeted RC24 fault-injection tests; original 297 tests unchanged.
