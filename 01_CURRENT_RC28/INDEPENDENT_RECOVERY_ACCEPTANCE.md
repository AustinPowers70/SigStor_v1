# Independent recovery acceptance protocol (not yet passed)

## Architecture boundary
Recovery observer must execute on an independent physical host or qualified inverter-native fail-safe, not in the Thor LXC or another VM on Thor. Control communications, power, observation and watchdog continuity must survive the tested failure mode. Do not assert independence from separate containers on the same machine.

## Commissioning procedure (requires separate operator approval)
1. Commission authenticated producer-to-supervisor heartbeat with monotonic expiry tied to a particular supervised session and arm/disarm handshake.
2. Verify supervisor owns a recovery-only write path with exclusive authority and bounded registers; forbid 40034.
3. Confirm commissioned return-to-self-consumption command sequence and actual readbacks: PCS demand=0, PCS mode=2, Remote EMS=0, with independent physical/power observation.
4. Inject loss of LXC process, Thor host, control network, recovery network, missed heartbeats, delayed/duplicated heartbeat and conflicting writer; record detections, outcomes and worst-case latency.
5. Verify supervisory recovery and post-fault no-restart latch; obtain operator-reviewed evidence before enabling any session longer than already commissioned pilots.

## Explicit holds
No automatic recovery write path is shipped in RC22. No authenticated heartbeat service or externally verified attestation exists yet. A `True` callback in offline tests cannot constitute physical recovery proof. RC13 economic decisions are not execution authority. No unattended trading.
