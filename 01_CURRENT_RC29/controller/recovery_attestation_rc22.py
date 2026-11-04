#!/usr/bin/env python3
"""RC22 recovery witness contract. No Modbus, service, or live execution APIs.

Attestation verification MUST be supplied by an independently deployed,
commissioned verifier. The struct alone is neither proof nor authorization.
"""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import hashlib, json, os, stat
from pathlib import Path
from recovery_latch_rc21 import RecoveryLatch, RecoveryRequired

@dataclass(frozen=True)
class RecoveryAttestation:
    session_id: str
    latch_digest: str
    witness_id: str
    observed_utc: datetime
    remote_ems_off: bool
    self_consumption: bool
    pcs_demand_zero: bool
    independent_of_thor: bool
    evidence_id: str

class AttestedRecoveryLatch(RecoveryLatch):
    """RC21 persistence plus strict external-attestation verification boundary."""
    def clear_after_independent_recovery(self, *args, **kwargs):
        raise RecoveryRequired('RC21 boolean-proof clearance retired; RC22 attestation required')

    def challenge(self):
        fd=os.open(self.path, os.O_RDONLY|os.O_NOFOLLOW)
        try:
            s=os.fstat(fd)
            if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_size>4096:raise RecoveryRequired('invalid latch')
            data=os.read(fd,4097)
            if len(data)>4096:raise RecoveryRequired('oversized latch')
            marker=json.loads(data)
            if marker.get('schema')!='SIGEN_RC21_RECOVERY_LATCH':raise RecoveryRequired('unrecognized latch')
            return marker['session_id'],hashlib.sha256(data).hexdigest()
        finally:os.close(fd)

    def clear_with_attestation(self, evidence, operator_ack, external_verifier, now=None):
        # Fail closed before any marker mutation.
        if not isinstance(evidence,RecoveryAttestation):raise RecoveryRequired('typed evidence required')
        if operator_ack is not True:raise RecoveryRequired('operator acknowledgement required')
        if not callable(external_verifier):raise RecoveryRequired('external verifier required')
        now=datetime.now(timezone.utc) if now is None else now
        if not isinstance(now,datetime) or now.tzinfo is None:raise RecoveryRequired('invalid current clock')
        t=evidence.observed_utc
        if not isinstance(t,datetime) or t.tzinfo is None:raise RecoveryRequired('timezone-aware evidence required')
        age=(now-t).total_seconds()
        if not -5<=age<=30:raise RecoveryRequired('stale or future evidence')
        if any(type(v) is not bool or not v for v in (evidence.remote_ems_off,evidence.self_consumption,evidence.pcs_demand_zero,evidence.independent_of_thor)):
            raise RecoveryRequired('physical handback proof incomplete')
        if not evidence.witness_id or not evidence.evidence_id:raise RecoveryRequired('missing witness identity')
        session,digest=self.challenge()
        if evidence.session_id!=session or evidence.latch_digest!=digest:raise RecoveryRequired('attestation not bound to active latch')
        # A real externally hosted proof verifier must authenticate the witness
        # and underlying readbacks. In tests this is a fake, not commissioning.
        if external_verifier(evidence) is not True:raise RecoveryRequired('external verifier denied')
        # Recheck to limit TOCTOU while clearing. RC21 inode matching remains.
        if self.challenge()!=(session,digest):raise RecoveryRequired('latch changed during verification')
        self._clear_matching(session)
