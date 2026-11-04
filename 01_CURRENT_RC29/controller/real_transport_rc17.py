#!/usr/bin/env python3
"""Phase 3B real-transport adapter, staged without a live dispatch entry point.

Operator session control must first implement approval, lock, isolated authority,
reserve/expiry enforcement, sampling and independent physical oversight. This
module does not assert those gates, and refuses to initiate a power command.
"""
from commissioning_transport_rc16 import RestrictedPlant, CommissioningBlocked
from actuator_contract_rc14 import PlantSequence

class LiveTransportUnavailable(RuntimeError): pass

class SupervisedPlantAdapter:
    """Adapt commissioned Modbus transport to the restricted register contract.

    Construction is intentionally impossible without an injected connection.
    The calling session MUST own the connection, operator approval and handback.
    No command-start method is exposed on this adapter.
    """
    def __init__(self,connection,audit):
        if connection is None or getattr(connection,'simulation_only',False) is True:
            raise LiveTransportUnavailable('requires an injected real Modbus connection')
        for method in ('read_holding','call','write','write_u32','close'):
            if not callable(getattr(connection,method,None)):
                raise LiveTransportUnavailable('missing Modbus method: '+method)
        self._restricted=RestrictedPlant(connection,audit)
        self._closed=False
    def read_holding(self,register):return self._restricted.read_holding(register)
    def read_pcs_demand_zero(self):
        import struct
        result=self._restricted.call(3,struct.pack('>HH',40001,2))
        return result==b'\x04\x00\x00\x00\x00'
    def close(self):
        if not self._closed:
            self._closed=True
            self._restricted.close()
    def start(self,*args,**kwargs):
        raise LiveTransportUnavailable('RC17 production full-slot actuation not authorised')
    def write(self,*args,**kwargs):
        raise LiveTransportUnavailable('RC17 direct write entry point disabled')
    def write_u32(self,*args,**kwargs):
        raise LiveTransportUnavailable('RC17 direct write entry point disabled')

def preview_handback_contract(connection,audit):
    """No commands: read-only assessment of two handback preconditions."""
    plant=SupervisedPlantAdapter(connection,audit)
    try:
        off=plant.read_holding(40029)==0
        mode=plant.read_holding(40031)==2
        pcs_zero=plant.read_pcs_demand_zero()
        return {'remote_ems_off':off,'self_consumption':mode,'pcs_zero':pcs_zero,
                'handback_state_verified':all((off,mode,pcs_zero)),
                'modbus_writes':0,'live_execution_enabled':False}
    finally:plant.close()

def main():
    print('RC17 REAL TRANSPORT STAGED: LIVE EXECUTION DISABLED; MODBUS_WRITES=0')
    return 2
if __name__=='__main__':raise SystemExit(main())
