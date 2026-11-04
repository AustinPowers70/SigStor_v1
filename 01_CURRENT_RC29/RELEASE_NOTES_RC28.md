# RC28 - manual commissioning-only pilot eligibility
- RC27 failed at HOLD_OUTSIDE_HORIZON even when an operator wanted a bounded physical test. RC28 removes economic-slot precondition **only for commissioning**.
- RC13 optimiser and all normal tariff qualification remain unchanged.
- Existing Modbus control sequences are reused via injected qualification functions, with original default qualification retained.
- Installation remains nonactuating; 12 targeted tests. Requires explicit local operator live approval for each pilot.
- Does not address Thor host/network loss, no full-slot or unattended permission.
