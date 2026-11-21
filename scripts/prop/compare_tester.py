import sys; sys.path.insert(0,'.')
import numpy as np, pandas as pd, datetime as dt
import strategies as S
SP='/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/'
q=S.load('../../data/prop/QQQ_5m.csv.gz'); q=q[q.date>=dt.date(2025,9,1)]
D=q.groupby('date').agg(o=('open','first'),c=('close','last'))
v=D.c.pct_change().rolling(14).std().shift(1)
# instrument noise_momentum: patch trades to record times by wrapping dict
orig=dict
rec=[]
src=open('strategies.py').read()
src=src.replace("trades.append(dict(pnl_pts=pos * (b.close - entry) * NQ_PER_QQQ,","trades.append(dict(et=et, xt=ts, side=pos, pnl_pts=pos * (b.close - entry) * NQ_PER_QQQ,")
src=src.replace("pos, entry, mae = 1, b.close, 0.0","pos, entry, mae, et = 1, b.close, 0.0, ts").replace("pos, entry, mae = -1, b.close, 0.0","pos, entry, mae, et = -1, b.close, 0.0, ts")
src=src.replace("trades.append(dict(pnl_pts=pos * (x.close.iloc[-1] - entry)","trades.append(dict(et=et, xt=x.index[-1], side=pos, pnl_pts=pos * (x.close.iloc[-1] - entry)")
ns={}; exec(compile(src,'s','exec'),ns)
tr=ns['noise_momentum'](q)
rows=[]
for day,ts in tr.items():
    if day<dt.date(2025,11,1): continue
    vs=min(2,0.012/v[day]); f=25000/(D.o[day]*41)*vs*12
    for t in ts: rows.append(dict(d=day,et=(t['et']+pd.Timedelta(minutes=5)).strftime('%H:%M'),xt=(t['xt']+pd.Timedelta(minutes=5)).strftime('%H:%M'),side=t['side'],py=t['pnl_pts']*f-1.5*12*vs))
P=pd.DataFrame(rows); P.to_pickle(SP+'py_trades.pkl')
# EA
d=pd.read_pickle(SP+'deals.pkl')
d['ts']=pd.to_datetime(d.Time,format='%Y.%m.%d %H:%M:%S')
for c in ['Profit','Commission','Volume','Price']: d[c]=pd.to_numeric(d[c].astype(str).str.replace(' ',''),errors='coerce')
ins=d[d.Direction=='in'].reset_index(drop=True); outs=d[d.Direction=='out'].reset_index(drop=True)
E=pd.DataFrame(dict(ets=ins.ts,side=np.where(ins.Type=='buy',1,-1),lots=ins.Volume,ep=ins.Price,xts=outs.ts,xp=outs.Price,ea=outs.Profit+outs.Commission.fillna(0)+ins.Commission.fillna(0)))
# server->NY: server is UTC+2/+3 EU DST; NY US DST
import pytz
def s2ny(t):
    eu = (t>=pd.Timestamp(t.year,3,31-(dt.date(t.year,3,31).weekday()+1)%7,3)) and (t<pd.Timestamp(t.year,10,31-(dt.date(t.year,10,31).weekday()+1)%7,4))
    utc=t-pd.Timedelta(hours=3 if eu else 2)
    return pytz.utc.localize(utc.to_pydatetime()).astimezone(pytz.timezone('America/New_York')).replace(tzinfo=None)
E['ent']=E.ets.map(s2ny); E['ext']=E.xts.map(s2ny); E['d']=E.ent.dt.date
E['et']=E.ent.dt.strftime('%H:%M'); E['xt']=E.ext.dt.strftime('%H:%M')
E.to_pickle(SP+'ea_trades.pkl')
print('EA net',E.ea.sum(),'PY net',P.py.sum())
de=E.groupby('d').agg(ea=('ea','sum'),en=('ea','size'),es=('side',lambda s:''.join('L' if a>0 else 'S' for a in s)),eet=('et',lambda s:','.join(s)),ext=('xt',lambda s:','.join(s)))
dp=P.groupby('d').agg(py=('py','sum'),pn=('py','size'),ps=('side',lambda s:''.join('L' if a>0 else 'S' for a in s)),pet=('et',lambda s:','.join(s)),pxt=('xt',lambda s:','.join(s)))
M=de.join(dp,how='outer').fillna({'ea':0,'py':0,'en':0,'pn':0})
M['diff']=M.ea-M.py
M.to_pickle(SP+'cmp.pkl')
same=(M.es==M.ps)
print('days',len(M),'same side seq',same.sum(),'EA only',M.ps.isna().sum(),'PY only',M.es.isna().sum())
print('diff on same-seq days',M.diff[same].sum(),' on different days',M.diff[~same].sum())
pd.set_option('display.width',250)
print(M.sort_values('diff').head(15)); print(M.sort_values('diff').tail(8))
