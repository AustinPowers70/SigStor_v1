import sys,struct,types,pathlib,tempfile,json
sys.path.insert(0,'/opt/sigenstor/scripts/phase3b-supervised-rc29/controller')
import supervised_export as se, commissioning_controller_rc28 as cc

class Plant:
    log=[];regs={40029:0,40031:2,40001:0,40032:0};soc=66.2;fail_on=None
    def __init__(s,host,timeout=3):Plant.log.append(('connect',))
    def close(s):pass
    def write(s,a,v):
        if Plant.fail_on==a:Plant.fail_on=None;raise TimeoutError('sim timeout on %d'%a)
        Plant.log.append(('W16',a,v));Plant.regs[a]=v
    def write_u32(s,a,v):Plant.log.append(('W32',a,v));Plant.regs[a]=v
    def read_holding(s,a):return Plant.regs[a]
    def call(s,fc,p):
        a,n=struct.unpack('>HH',p);assert fc==3 and a==40001 and n==2
        return bytes([4])+struct.pack('>I',Plant.regs[40001])
    def soc_(s):return Plant.soc
Plant.soc=lambda s:Plant.soc_v
Plant.soc_v=66.2

def run(scenario):
    Plant.log=[];Plant.regs={40029:0,40031:2,40001:0,40032:0};Plant.soc_v=66.2;Plant.fail_on=None
    panel={'active':True};events=[]
    def systemctl(cmd,unit):
        if cmd=='stop':panel['active']=False
        if cmd=='start':panel['active']=True
        return types.SimpleNamespace(returncode=0 if (cmd!='is-active' or panel['active']) else 3,stdout='active' if panel['active'] else 'inactive',stderr='')
    def permit(action,phase):
        return {'Decision':action,'StartUtc':'MANUAL_COMMISSIONING_30S','AuthorityManualReady':True},20
    t=[0.0]
    def clock():return t[0]
    def sleep(x):
        t[0]+=x
        if scenario=='soc_drop' and t[0]>10:Plant.soc_v=21.5
    lock=pathlib.Path(tempfile.mkdtemp())/'l.lock'
    if scenario=='first_write_timeout':Plant.fail_on=40029
    try:
        se.perform_export(qualify=None,systemctl=systemctl,audit=lambda e,d='':events.append(e),lock=lock,auth_unit='u',host='h',
            plant_cls=Plant,handback=lambda h:se.export_handback(h,plant_cls=Plant,sleep=lambda s:None),sleep=sleep,clock=clock,
            qualification=lambda ph:permit('EXPORT',ph))
        out='OK'
    except Exception as e:out='RAISED: '+str(e)
    writes=[x for x in Plant.log if x[0]!='connect']
    print(f'\n== {scenario}: {out}\n writes={writes}\n final={Plant.regs} panel_active={panel["active"]}\n audit={events}')
    assert all(w[1]!=40034 for w in writes),'40034 WRITTEN'
    assert Plant.regs[40029]==0 and Plant.regs[40031]==2 and Plant.regs[40001]==0,'NOT HANDED BACK'
for s in ('nominal','soc_drop','first_write_timeout'):run(s)

# Handback failure: plant refuses to release Remote EMS -> panel must stay isolated, CRITICAL raised.
_orig=Plant.write
def stuck(s,a,v):
    if a==40029 and v==0:raise TimeoutError('sim: EMS release refused')
    _orig(s,a,v)
Plant.write=stuck
try:run('handback_fails')
except AssertionError as e:print('  expected assertion (plant NOT handed back):',e)
