"""Effect of the EA's margin cap (<=80% of free margin) at different index leverage levels.
Notional at $D/pt (constant-notional, index 25000) x vol multiplier = D*25000*m; cap m so that
notional <= 0.8 * leverage * equity (equity ~ initial)."""
import pickle, numpy as np, pandas as pd
from strategies import load
from propsim import ftmo2, ftmo_funded_dyn
P = "/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/"
raw = pickle.load(open(P + "trades.pkl", "rb"))["noise_vwap"]
q = load("../../data/prop/QQQ_5m.csv.gz")
d = q.groupby("date").agg(o=("open", "first"), c=("close", "last"))
vol = d.c.pct_change().rolling(14).std().shift(1); lvl = d.o * 41.0
def build(D, lev):
    out = {}
    for day, trs in raw.items():
        s = vol.loc[day]
        if not np.isfinite(s): continue
        m = min(2.0, 0.012 / s)
        if lev: m = min(m, 0.8 * lev * 100000 / (D * 25000))
        f = 25000 / lvl.loc[day] * m
        out[day] = [dict(pnl_pts=t["pnl_pts"] * f, mae_pts=t["mae_pts"] * f, risk_pts=1) for t in trs]
    ds = sorted(out); return [out[x] for x in ds]
for lev in (None, 20, 10, 7, 5):
    e = build(12, lev); o = [ftmo2(e, s, 12) for s in range(0, len(e) - 300, 2)]
    p = [x for x in o if x[0] == "pass"]
    fu = build(8, lev); f = [ftmo_funded_dyn(fu, s, 8, power=1) for s in range(0, len(fu) - 252, 5)]
    print(f"leverage {lev or 'none'}: eval $12 pass {100*len(p)/len(o):.0f}% median {np.median([x[1] for x in p]):.0f}d | funded $8 scaled ${np.mean([x[0] for x in f])/1000:.1f}k/yr breach {100*np.mean([x[1]=='breach' for x in f]):.0f}%")
