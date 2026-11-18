"""Part 2: how unusual are the last-12m regime metrics vs 2016-23 rolling windows, and does a trailing
regime filter (chosen on 2016-21) help out-of-sample (2022-26)?"""
import numpy as np, pandas as pd
SP="/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/"
T=pd.read_pickle(SP+"regime_T.pkl"); M=pd.read_pickle(SP+"regime_M.pkl")
M.index=pd.to_datetime(M.index); T["d"]=pd.to_datetime(T.d)
M["late_x"]=np.sign(M.early+M.mid)*M.late   # late-day continuation (>0 momentum)
M["trendf"]=M.trend.astype(float)
for col in ["gap_share","trendf","vr","eff","ac30","late_x","rv"]:
    r=M[col].rolling(252).mean().dropna(); h=r[r.index<"2024-01-01"]; last=r.iloc[-1]
    print(f"{col:10s} last12m {last:+.4f} | 2016-23 12m windows p5 {h.quantile(.05):+.4f} med {h.median():+.4f} p95 {h.quantile(.95):+.4f} | pct rank {(h<last).mean():.0%}")
daily=T.groupby("d").pnl.sum().reindex(M.index,fill_value=0.0)
# trailing-60d regime features known before the open
F=pd.DataFrame({k:M[k].rolling(60).mean().shift(1) for k in ["gap_share","trendf","vr","eff","late_x"]})
F["pnl"]=daily
F=F.dropna()
IS=F.index<"2022-01-01"; OS=~IS
print("\nfilter: half size when trailing-60d feature is in its worst IS tercile (by IS P&L)")
for k in ["gap_share","trendf","vr","eff","late_x"]:
    qs=F[IS][k].quantile([1/3,2/3]).values; b=np.digitize(F[k],qs)
    isp=[F[IS&(b==i)].pnl.mean() for i in range(3)]; osp=[F[OS&(b==i)].pnl.mean() for i in range(3)]
    worst=int(np.argmin(isp)); m=np.where(b==worst,0.5,1.0)
    adj=F.pnl*m
    def s(x): return x.mean()/x.std()*np.sqrt(252)
    print(f"{k:10s} IS $/day by tercile {[round(v) for v in isp]} OS {[round(v) for v in osp]} | worst={worst} "
          f"OS sharpe base {s(F.pnl[OS]):.2f} -> {s(adj[OS]):.2f}, OS $/yr {F.pnl[OS].sum()/4.87:,.0f} -> {adj[OS].sum()/4.87:,.0f}")
