# RC29 (revision b): Separating evidence quality from plant recovery, plus operator-witnessed latch closure

**What this fixes:** On 4 Nov 2026, session `8d39f77fc0e244b69f79f0257b56ba07` ended as `HOLD_RECOVERY_REQUIRED`. The cause was one AFTER-phase sample flagged `home_kw:implausible`. The RC27 verdict treated "the evidence is imperfect" the same as "plant recovery is unproven".

## Changes
1. **`attended_commissioning_rc27.py`**: the verdict now produces two separate results, `handback_proven` and `evidence_complete`.
   - Both true: `SUPERVISED_PILOT_HANDBACK_CONFIRMED`, and the latch auto-clears. This rule is unchanged and just as strict.
   - Handback proven but evidence degraded: **`HOLD_EVIDENCE_REVIEW_HANDBACK_VERIFIED`**. The latch is **retained**.
   - Otherwise: `HOLD_RECOVERY_REQUIRED`, as before.
   - The result also records `invalid_by_phase` and `invalid_reasons`.
2. **New file `latch_closure_rc29.py`**: operator-witnessed closure. It **never writes to Modbus**.
   - `--status`: shows the latch only, without contacting the plant.
   - `--review`: read-only.
     - **Evidence check** on the **hash-verified** trace `rc27-pilot-<session>.jsonl`:
       - **complete lifecycle (RC29b):** exactly one each of `SESSION_LATCH_ARMED`, `DELEGATE_STARTED`, `DELEGATE_EXIT`, `POST_HAND_BACK` and `SESSION_RESULT`, in that order. Every event carries this session's ID, and no other event types are allowed (so CRITICAL events are rejected);
       - **cross-checks (RC29b):** `DELEGATE_EXIT.returncode` must equal `SESSION_RESULT.live_controller_exit`, and both must be 0. `POST_HAND_BACK.plant_ok` and `panel_ok` must match the result's `plant_handback_verified` and `panel_restored`, and all must be true. The armed action must equal the result action;
       - no delegate timeout and no observer error;
       - minimum valid samples: 2 BEFORE, 5 DURING, 2 AFTER;
       - at most 2 invalid samples, **none during actuation**, and **only** `home_kw:implausible` (any other flag rejects the review).
     - **Plant check**: 3 fresh FC03/FC04 readbacks, each showing Remote EMS off, mode 2 and PCS request 0. The authority panel must be active and the controller lock free.
     - Writes a review record that expires after 10 minutes and stores SHA-256 hashes of the latch and trace.
   - `--close --operator-ack`:
     - **takes the exclusive controller lock (`/run/lock/sigen-rtm-v12-commission.lock`, non-blocking) before anything else and holds it until the latch has been removed and audited (RC29b).** If the lock is busy, the tool refuses before any plant read. While it's held, no cooperating controller can start: not during the challenge, the final readbacks, the record write or the latch removal;
     - requires a local TTY and the typed challenge `CLEAR RECOVERY LATCH <session[:12]>`;
     - requires an unexpired, eligible review whose latch and trace hashes still match;
     - repeats the fresh plant readback;
     - fsyncs a write-once `CLOSURE_AUTHORISED` record (O_EXCL, mode 0400) **before** calling `RecoveryLatch.clear_after_independent_recovery`, then writes `LATCH_CLEARED`.

## Unchanged
- Latch path `rc28-recovery-required.json`, so the existing latch still blocks new sessions.
- The RC13 economic optimiser, Modbus registers, the never-write rule for 40034, and the 500 W and 650 W pilot sequences.
- No autonomous dispatch.

## Limits
- **Hash-verified, not immutable.** Root can still edit the trace and the closure records. The SHA-256 check only detects changes made between `--review` and `--close`.
- **The lock only excludes cooperating entry points** (controller.py and the RC28 child). Exclusion across every writer on the system is still unproven, as noted in the architecture doc.
- **Phase labelling race:** a sample taken during a phase change can carry the earlier phase label. Its only effect is to make a review fail closed.
- This is **not** host-loss recovery and **not** proof of battery-attributable grid-side energy.
- Closing the latch **does not authorise** any further pilot. The 650 W export test still needs separate new approval.
- The allowlist is deliberately narrow. Widening it needs a code change and review.

## Tests
- `tests/test_rc29.py`: 31 tests (the original RC29 tests, with fixtures updated to real RC27 event fields).
- `tests/test_rc29b.py`: 22 targeted tests:
  - each required event missing, duplicated or attributed to another session;
  - out-of-order sequences, unexpected events, and exit-code and handback contradictions in both directions;
  - the lock held during every final readback, the operator challenge and latch removal, with the closure record written before removal;
  - a busy lock blocks closure before any readback, and the lock is released after a failure;
  - a symlinked lock is rejected;
  - an end-to-end trace from the real RC27 `orchestrate`/`Observation`/`append` code passes the lifecycle checks.
- Full suite run once as a sanity check: see `rc29_test.log`. Offline simulation only.
