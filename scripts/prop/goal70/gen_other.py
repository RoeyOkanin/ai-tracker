import sys, pickle, numpy as np, pandas as pd
sys.path.insert(0, "..")
import strategies as S
from gen_trades import prep, noise_trades, SP
out = {}
for sym in ("SPY", "IWM", "DIA", "GLD"):
    q = S.load(f"../../../data/prop/{sym}_5m.csv.gz")
    days, g = prep(q)
    gd = q.groupby("date"); Dx = pd.DataFrame(dict(o=gd.open.first(), c=gd.close.last())); Dx["vol14"] = Dx.c.pct_change().rolling(14).std().shift(1)
    tr = noise_trades(days, g, block=("12:00", "14:00"))
    # daily P&L as % of notional, vol-scaled (cap 1), cost 0.02% of notional per trade (~5 NQ pts at 25000)
    pnl = {}
    for d, ts in tr.items():
        v = Dx.vol14.get(d)
        if v is None or not np.isfinite(v): continue
        vs = min(1.0, 0.012 / v); o = Dx.o[d]
        pnl[d] = sum(vs * (t["pts"] / S.NQ_PER_QQQ / o - 0.0002) for t in ts)
    out[sym] = pd.Series(pnl)
    print(sym, len(out[sym]), flush=True)
pickle.dump(out, open(SP + "g70_other.pkl", "wb"))
