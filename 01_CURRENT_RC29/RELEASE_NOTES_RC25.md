# RC25 — Rehearsal/live separation and commissioning evidence review

RC24 was independently validated on Thor (302/302), with no active services or inverter writes. RC25 explicitly rejects real/untagged Modbus adapters at the attended-pilot *injection-only* API. The offline test fixture is explicitly tagged `simulation_only=True`. This is a guard against accidental binding, not a cryptographic trust boundary: Python caller code can still impersonate fake adapters; therefore RC25 is not a live execution controller.

A new read-only assessor accepts a JSONL list of event/detail envelopes and reports sequence completeness and sample-event coverage. It deliberately **never** upgrades audit events or aggregate grid power into verified physical grid-side battery delivery. A complete simulated audit remains simulated evidence only.

No new systemd services, autonomous dispatch, real actuator CLI or changes to RC13, 40034, 500 W charge and 650 W export limits. Independently verified host-loss recovery remains unresolved and full-slot control not commissioned.
