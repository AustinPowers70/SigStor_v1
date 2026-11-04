#!/usr/bin/env python3
"""RC14 production-protocol actuator contract. NOT a live execution entry point.

Tests use an injected plant double. A real plant is deliberately not instantiated
or connected by this module. Runtime commissioning remains disabled.
"""
import math

class ActuatorContractError(RuntimeError): pass
LIMITS={'GRID_CHARGE':500, 'EXPORT':650}

class PlantSequence:
    """Command transaction with ambiguous-write handback responsibility.

    All register access goes through the injected plant object. A successful
    response from a write is NOT proof of delivered power.
    """
    def __init__(self,plant):
        self.plant=plant
        self.attempted=False
    def start(self, action, watts):
        if action not in LIMITS or type(watts) is not int or watts!=LIMITS[action]:
            raise ActuatorContractError('only exact commissioned setpoints supported')
        if self.attempted: raise ActuatorContractError('start already attempted')
        if self.plant.read_holding(40029)!=0:
            raise ActuatorContractError('Remote EMS already held')
        self.attempted=True  # first write may time out after execution
        if action=='GRID_CHARGE':
            self.plant.write_u32(40032,500)
            self.plant.write(40031,3)
            self.plant.write(40029,1)
        else:
            self.plant.write(40029,1)
            self.plant.write(40031,0)
            self.plant.write_u32(40001,650)
        if self.plant.read_holding(40029)!=1:
            raise ActuatorContractError('Remote EMS enable not verified')
        if self.plant.read_holding(40031)!=(3 if action=='GRID_CHARGE' else 0):
            raise ActuatorContractError('plant mode mismatch')
    def handback(self):
        """Strict common charge/export handback including PCS-zero verification.

        Never hide failures. Caller owns bounded retries and authority isolation.
        """
        failures=[]
        for fn in (lambda:self.plant.write_u32(40001,0),
                   lambda:self.plant.write(40031,2),
                   lambda:self.plant.write(40029,0)):
            try:fn()
            except Exception as exc:failures.append(type(exc).__name__)
        try:
            off=self.plant.read_holding(40029)==0
            mode=self.plant.read_holding(40031)==2
            import struct
            words=self.plant.call(3,struct.pack('>HH',40001,2))
            zero=len(words)==5 and words==b'\x04\x00\x00\x00\x00'
        except Exception:
            return False
        return not failures and off and mode and zero

def operator_policy(*,operator_approval,manual_authority,exclusive_lock,
                    authority_isolated,rc13_research_only,source_fresh,
                    slot_active,reserve_ok,telemetry_ready):
    """Explicit policy independent of research-only RC13 dispatch flag.

    This reports prerequisites, NOT permission for live writes. The executable
    live gate is absent from RC14 by design.
    """
    values=locals()
    if any(type(v) is not bool for v in values.values()):
        raise ActuatorContractError('policy flags must be boolean')
    return {'prerequisites_met':all(values.values()),'production_execution_enabled':False,
            'operator_live_authorisation_accepted':False,'modbus_writes':0}

def main():
    print('RC14_ACTUATOR_CONTRACT_ONLY: LIVE_EXECUTION_DISABLED MODBUS_WRITES=0')
    return 2
if __name__=='__main__':raise SystemExit(main())
