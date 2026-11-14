"""Score grid variants: IS 2016-2021 vs OOS 2022-2026 on vol-targeted, constant-notional daily P&L."""
import pickle, glob, os, numpy as np, pandas as pd
from strategies import load
P = "/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/grid/"
_cache = {}
def dailyinfo(sym):
    if sym not in _cache:
        q = load(f"../../data/prop/{sym}_5m.csv.gz")
        d = q.groupby("date").agg(o=("open", "first"), c=("close", "last"))
        _cache[sym] = (d.o * 41.0, d.c.pct_change().rolling(14).std().shift(1))
    return _cache[sym]
def norm(v, sym, target=0.012):
    lvl, vol = dailyinfo(sym)
    out = {}
    for d, trs in v.items():
        s = vol.loc[d]
        if not np.isfinite(s): continue
        f = 25000.0 / lvl.loc[d] * min(2.0, target / s)
        out[d] = [dict(pnl_pts=t["pnl_pts"] * f, mae_pts=t["mae_pts"] * f, risk_pts=t["risk_pts"] * f) for t in trs]
    return out
COST = 1.5
def daily(v):
    ds = sorted(v)
    return pd.Series([sum(t["pnl_pts"] - COST for t in v[d]) for d in ds], index=pd.to_datetime(ds))
def score(s):
    sh = lambda x: x.mean() / x.std() * 252 ** .5
    is_, oos = s[s.index.year <= 2021], s[s.index.year >= 2022]
    yr = s.groupby(s.index.year).sum()
    eq = s.cumsum(); dd = (eq - eq.cummax()).min()
    return dict(IS=round(sh(is_), 2), OOS=round(sh(oos), 2), ALL=round(sh(s), 2), yrs_pos=f"{(yr>0).sum()}/{len(yr)}",
                pts_day=round(s.mean(), 1), maxDD_pts=round(dd))
if __name__ == "__main__":
    rows = []
    for f in sorted(glob.glob(P + "*.pkl")):
        k = os.path.basename(f)[:-4]; sym = k.split("_")[0]
        v = norm(pickle.load(open(f, "rb")), sym)
        rows.append(dict(k=k, **score(daily(v))))
    df = pd.DataFrame(rows).sort_values("IS", ascending=False)
    print(df.to_string(index=False))
