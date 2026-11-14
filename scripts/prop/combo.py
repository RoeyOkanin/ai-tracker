"""Multi-market intraday momentum: same base rules (14d noise band, VWAP stop, 30-min checks) on
NQ/ES/RTY/YM/gold/oil proxies (QQQ/SPY/IWM/DIA/GLD/USO 5-min), equal risk via 1.2% vol target,
CFD spread costs per instrument, then the portfolio is rescaled to the same daily risk as NQ alone
so FTMO $/pt sizing stays comparable."""
import os, sys, pickle, numpy as np, pandas as pd
from strategies import load, noise_momentum
from propsim import ftmo2, ftmo_funded, summarize
P = "/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/"
# round-turn cost as a fraction of notional (CFD spread x1.5 safety)
COST = {"QQQ": 0.00006, "SPY": 0.00009, "IWM": 0.0003, "DIA": 0.00007, "GLD": 0.00015, "USO": 0.0006}
syms = [s for s in COST if os.path.exists(f"../../data/prop/{s}_5m.csv.gz")]
S = {}
for s in syms:
    q = load(f"../../data/prop/{s}_5m.csv.gz")
    f = P + f"base_{s}.pkl"
    v = pickle.load(open(f, "rb")) if os.path.exists(f) else noise_momentum(q)
    pickle.dump(v, open(f, "wb"))
    d = q.groupby("date").agg(o=("open", "first"), c=("close", "last"))
    lvl, vol = d.o * 41.0, d.c.pct_change().rolling(14).std().shift(1)
    pnl, mae = {}, {}
    for day, trs in v.items():
        sg = vol.loc[day]
        if not np.isfinite(sg): continue
        fx = 25000.0 / lvl.loc[day] * min(2.0, 0.012 / sg)
        pnl[day] = sum(t["pnl_pts"] * fx - COST[s] * 25000 * min(2.0, 0.012 / sg) for t in trs)
        mae[day] = sum(min(t["mae_pts"], 0) * fx for t in trs)
    S[s] = (pd.Series(pnl), pd.Series(mae))
idx = sorted(set.intersection(*[set(S[s][0].index) for s in syms]))
R = pd.DataFrame({s: S[s][0].reindex(idx) for s in syms}).fillna(0)
M = pd.DataFrame({s: S[s][1].reindex(idx) for s in syms}).fillna(0)
R.index = pd.to_datetime(R.index); M.index = R.index
sh = lambda x: round(x.mean() / x.std() * 252 ** .5, 2)
print("period", R.index[0].date(), R.index[-1].date(), len(R))
print("per-instrument Sharpe (net):", {s: sh(R[s]) for s in syms})
print("OOS 2022+:", {s: sh(R[s][R.index.year >= 2022]) for s in syms})
print("correlation:\n", R.corr().round(2))
base_sd = R["QQQ"].std()
combos = {"NQ": ["QQQ"], "NQ+ES": ["QQQ", "SPY"], "4 indices": ["QQQ", "SPY", "IWM", "DIA"],
          "NQ+gold": ["QQQ", "GLD"], "NQ+ES+gold": ["QQQ", "SPY", "GLD"],
          "indices+gold": ["QQQ", "SPY", "IWM", "DIA", "GLD"], "all 6": syms}
out = {}
for name, cs in combos.items():
    cs = [c for c in cs if c in syms]
    p = R[cs].mean(axis=1); m = M[cs].mean(axis=1)
    k = base_sd / p.std(); p, m = p * k, m * k
    yr = p.groupby(p.index.year).sum()
    eq = p.cumsum()
    print(f"{name:14s} Sharpe {sh(p)} | IS {sh(p[p.index.year<=2021])} OOS {sh(p[p.index.year>=2022])} | yrs+ {(yr>0).sum()}/{len(yr)} | worst yr {yr.min():.0f} | maxDD {(eq-eq.cummax()).min():.0f} pts")
    out[name] = {d.date(): [dict(pnl_pts=p[d], mae_pts=min(m[d], p[d], 0), risk_pts=1)] for d in p.index}
pickle.dump(out, open(P + "combos.pkl", "wb"))
pick = sys.argv[1:] or ["NQ", "NQ+ES", "indices+gold"]
for name in pick:
    v = out[name]; ds = sorted(v); days = [v[d] for d in ds]
    print(f"\n## {name}")
    for dpp in (8, 12):
        o = [ftmo2(days, s, dpp, cost_pts=0) for s in range(0, len(days) - 300, 2)]
        md = np.median([x[1] for x in o if x[0] == "pass"]) if any(x[0] == "pass" for x in o) else None
        print(f"  eval ${dpp}/pt: {summarize(o)} median {md}")
    for dpp in (5, 8):
        f = [ftmo_funded(days, s, dpp, cost_pts=0) for s in range(0, len(days) - 252, 5)]
        print(f"  funded ${dpp}/pt: ${np.mean([x[0] for x in f]):,.0f}/yr, breach {100*np.mean([x[1]=='breach' for x in f]):.0f}%")
