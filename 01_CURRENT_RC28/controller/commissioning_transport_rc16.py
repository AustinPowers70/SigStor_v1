#!/usr/bin/env python3
"""RC16 isolated commissioning transport adapter.

Imports the validated supervised Modbus transport only through a supplied factory.
A transport can be created for fake-hardware tests but has NO exposed operator
live execution entry point. The installer never connects or writes to the plant.
"""
from actuator_contract_rc14 import PlantSequence, LIMITS

ALLOWED_SINGLE={40029:{0,1},40031:{0,2,3}}
ALLOWED_MULTI={40001:{0,650},40032:{500}}

class CommissioningBlocked(RuntimeError):
    pass

class RestrictedPlant:
    """Restricted register API with audited intent, fail-closed on other writes.

    This layer is NOT live authorisation. It requires a separate, future
    operator-authorised session controller and independent expiry recovery.
    """
    def __init__(self, connection, audit):
        if not callable(audit):raise CommissioningBlocked('audit callback required')
        self._connection=connection
        self._audit=audit
        self._closed=False
    def _check(self):
        if self._closed:raise CommissioningBlocked('transport closed')
    def read_holding(self, address):
        self._check()
        if type(address) is not int or address not in (40029,40031):
            raise CommissioningBlocked('non-allowlisted holding read')
        return self._connection.read_holding(address)
    def call(self, fc, payload):
        self._check()
        if fc!=3 or payload!=bytes.fromhex('9c410002'):
            raise CommissioningBlocked('only FC03 PCS zero read permitted')
        return self._connection.call(fc,payload)
    def write(self,address,value):
        self._check()
        if type(address) is not int or type(value) is not int or value not in ALLOWED_SINGLE.get(address,set()):
            raise CommissioningBlocked('write blocked by register allowlist')
        self._audit('WRITE_INTENT',{'register':address,'value':value,'function':6})
        try:self._connection.write(address,value)
        except BaseException:
            self._audit('WRITE_OUTCOME_UNCERTAIN',{'register':address})
            raise
        self._audit('WRITE_ACK',{'register':address})
    def write_u32(self,address,value):
        self._check()
        if type(address) is not int or type(value) is not int or value not in ALLOWED_MULTI.get(address,set()):
            raise CommissioningBlocked('u32 write blocked by register allowlist')
        self._audit('WRITE_INTENT',{'register':address,'value':value,'function':16})
        try:self._connection.write_u32(address,value)
        except BaseException:
            self._audit('WRITE_OUTCOME_UNCERTAIN',{'register':address})
            raise
        self._audit('WRITE_ACK',{'register':address})
    def close(self):
        if not self._closed:
            self._closed=True
            self._connection.close()

class OfflineTransportHarness:
    """The only RC16 constructible runner: simulator-tagged transport exclusively."""
    def __init__(self,conn,audit):
        if getattr(conn,'simulation_only',None) is not True:
            raise CommissioningBlocked('real transport cannot enter RC16 harness')
        self.plant=RestrictedPlant(conn,audit)
        self.sequence=PlantSequence(self.plant)
    def start(self,action):
        self.sequence.start(action,LIMITS[action])
    def handback(self):
        return self.sequence.handback()
    def close(self):self.plant.close()

def main():
    print('RC16 COMMISSIONING TRANSPORT STAGED: LIVE_EXECUTION_DISABLED MODBUS_WRITES=0')
    return 2
if __name__=='__main__':raise SystemExit(main())
