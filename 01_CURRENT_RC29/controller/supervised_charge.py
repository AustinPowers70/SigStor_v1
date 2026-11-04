#!/usr/bin/env python3
"""Supervised live Modbus commission: bounded 0.5 kW charge and guaranteed local handback attempt.
This is NOT an unattended controller or independent safety mechanism.
"""
import argparse, contextlib, socket, struct, sys, time
HOST='192.168.0.8'; PORT=502; UNIT=247
class Modbus:
    def __init__(self,host,timeout=3):
        self.s=socket.create_connection((host,PORT), timeout); self.s.settimeout(timeout); self.tx=0
    def close(self): self.s.close()
    def call(self,fc,payload):
        self.tx=(self.tx+1)%65536
        pdu=bytes([fc])+payload
        self.s.sendall(struct.pack('>HHHB',self.tx,0,len(pdu)+1,UNIT)+pdu)
        header=self.recv(7); tid,proto,length,unit=struct.unpack('>HHHB',header)
        if tid!=self.tx or proto!=0 or unit!=UNIT or length<2 or length>256: raise RuntimeError('Invalid Modbus TCP response header')
        ans=self.recv(length-1)
        if ans[0]==(fc|128): raise RuntimeError(f'Modbus exception {ans[1]} on FC{fc}')
        if ans[0]!=fc: raise RuntimeError('Unexpected function response')
        return ans[1:]
    def recv(self,n):
        buf=b''
        while len(buf)<n:
            part=self.s.recv(n-len(buf))
            if not part: raise ConnectionError('Modbus connection closed')
            buf+=part
        return buf
    def write_u32(self,address,value):
        payload=struct.pack('>HHB I',address,2,4,value)
        res=self.call(16,payload)
        if res!=struct.pack('>HH',address,2): raise RuntimeError('Write multiple response mismatch')
    def read_holding(self,address):
        res=self.call(3,struct.pack('>HH',address,1))
        if res[0]!=2: raise RuntimeError('Invalid register byte count')
        return struct.unpack('>H',res[1:3])[0]
    def write(self,address,value):
        res=self.call(6,struct.pack('>HH',address,value))
        if res!=struct.pack('>HH',address,value): raise RuntimeError('Write echo mismatch')
    def soc(self):
        # Confirmed plant FC04 30005 / 34; SOC at data byte offsets 18,19.
        res=self.call(4,struct.pack('>HH',30005,34))
        if res[0]!=68: raise RuntimeError('Unexpected SOC block length')
        value=struct.unpack('>H',res[1+18:1+20])[0]/10
        if not (0<=value<=100):raise RuntimeError('SOC outside 0-100%')
        return value

def handback(host):
    errors=[]
    for attempt in range(3):
        try:
            con=Modbus(host)
            try:
                # Request explicit self-consumption before removing remote authority.
                # Continue the disable attempt if mode selection is ambiguous.
                errors=[]
                try: con.write(40031,2)
                except Exception as exc: errors.append(str(exc))
                try: con.write(40029,0)
                except Exception as exc: errors.append(str(exc))
                if con.read_holding(40029)!=0: raise RuntimeError('Remote EMS disable not verified')
                if con.read_holding(40031)!=2: raise RuntimeError('Self-consumption mode not verified')
                if errors: raise RuntimeError('Ambiguous handback write: '+repr(errors))
                print('HANDBACK_VERIFIED: Remote EMS disabled and self-consumption mode verified',flush=True)
                return True
            finally: con.close()
        except Exception as exc:
            errors.append(str(exc));time.sleep(1)
    print('CRITICAL: EMS HANDBACK NOT CONFIRMED. Check inverter locally immediately. '+repr(errors),file=sys.stderr,flush=True)
    return False


# Legacy standalone live charging CLI intentionally removed in RC6.
# All supervised commissioning must enter through controller.py.
if __name__ == "__main__":
    raise SystemExit("DIRECT_CHARGE_ENTRYPOINT_DISABLED: use centrally gated controller.py")
