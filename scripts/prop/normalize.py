"""Rescale per-day trades to today's NQ level (constant-notional view) and optionally
vol-target them (Concretum sizing: scale by target/realized 14-day daily vol, cap 2x)."""
import pickle, numpy as np, pandas as pd
from strategies import load
P = "/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/"
q = load("../../data/prop/QQQ_5m.csv.gz")
daily = q.groupby("date").agg(o=("open", "first"), c=("close", "last"))
ret = daily.c.pct_change()
vol14 = ret.rolling(14).std().shift(1)       # known before the open
lvl = daily.o * 41.0
NOW = 25000.0
res = pickle.load(open(P + "trades.pkl", "rb"))
out = {}
for k, v in res.items():
    for vt in (False, True):
        name = k + ("_vt" if vt else "")
        nv = {}
        for d, trs in v.items():
            f = NOW / lvl.loc[d]
            if vt:
                s = vol14.loc[d]
                if not np.isfinite(s):
                    continue
                f *= min(2.0, 0.012 / s)    # 1.2% ~ median daily vol of NQ
            nv[d] = [dict(pnl_pts=t["pnl_pts"] * f, mae_pts=t["mae_pts"] * f, risk_pts=t["risk_pts"] * f) for t in trs]
        out[name] = nv
pickle.dump(out, open(P + "trades_norm.pkl", "wb"))
print(ret.std(), ret.median(), vol14.median())
