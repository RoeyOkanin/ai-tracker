import pickle, numpy as np, pandas as pd
res = pickle.load(open("/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/trades_norm.pkl", "rb"))
COST_PTS = 1.25  # per NQ contract round turn in NQ points (=$2.5/MNQ)
for k, v in res.items():
    rows = []
    for d, trs in v.items():
        for t in trs:
            rows.append(dict(d=pd.Timestamp(d), pnl=t["pnl_pts"] - COST_PTS, risk=t["risk_pts"]))
    df = pd.DataFrame(rows)
    if df.empty: continue
    r = df.pnl / df.risk.where(df.risk > 0)
    yr = df.groupby(df.d.dt.year).pnl.sum()
    print(f"{k:12s} n={len(df)} win={100*(df.pnl>0).mean():.0f}% avgpts={df.pnl.mean():.2f} "
          f"avgR={r.mean():.3f} medRisk={df.risk.median():.1f}pts")
    print("   pts/yr 1 NQ:", " ".join(f"{y%100}:{p:+.0f}" for y, p in yr.items()))
