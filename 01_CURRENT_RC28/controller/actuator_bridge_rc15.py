#!/usr/bin/env python3
"""OFFLINE ONLY: adapt exact commissioned register sequences into RC12 rehearsal.

No sockets, live Modbus sessions or live entry point. Requires an explicitly
simulation-tagged in-memory plant. Never converts RC13 research output to authority.
"""
from actuator_contract_rc14 import PlantSequence, LIMITS, ActuatorContractError

class BridgeError(RuntimeError): pass

class SimulatedActuatorBridge:
    simulation_only=True
    def __init__(self,plant):
        if type(getattr(plant,'simulation_only',None)) is not bool or plant.simulation_only is not True:
            raise BridgeError('injected plant must be simulation-only')
        self._sequence=PlantSequence(plant)
        self._started=False
        self._handback_attempted=False
    def start(self,action,rated_kw):
        if self._started: raise BridgeError('single start only')
        if type(rated_kw) not in (int,float) or action not in LIMITS:
            raise BridgeError('invalid setpoint')
        expected=LIMITS[action]
        if abs(rated_kw*1000-expected)>1e-8:
            raise BridgeError('only exact commissioned power allowed')
        self._started=True
        self._sequence.start(action,expected)
    def handback(self):
        if self._handback_attempted:raise BridgeError('handback already attempted')
        self._handback_attempted=True
        return self._sequence.handback() is True

def execute_rehearsal(**kwargs):
    """Run the existing RC12 supervisor against a fake plant and injected clock."""
    import supervised_rehearsal_rc12
    actuator=kwargs.get('actuator')
    if type(actuator) is not SimulatedActuatorBridge:
        raise BridgeError('RC15 only accepts simulated bridge')
    return supervised_rehearsal_rc12.run(**kwargs)

def main():
    print('RC15 SIMULATED PLANT BRIDGE ONLY; LIVE EXECUTION DISABLED; MODBUS_WRITES=0')
    return 2
if __name__=='__main__':raise SystemExit(main())
