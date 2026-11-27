"""FTMO Standard (non-Swing) check: funded Standard accounts may not open/close US100 within
2 minutes of restricted news. Variants move the 10:00 / 14:00 (/14:30) checkpoints 5 minutes later,
every day, so the EA never acts inside a 10:00 or 14:00 ET blackout. Also compares 2-Step vs 1-Step speed."""
import pickle, numpy as np, pandas as pd
from strategies import load, noise_momentum
from propsim import ftmo2, ftmo1, ftmo_funded, summarize
P = "/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/"
q = load("../../data/prop/QQQ_5m.csv.gz")
daily = q.groupby("date").agg(o=("open", "first"), c=("close", "last"))
vol14 = daily.c.pct_change().rolling(14).std().shift(1)
lvl = daily.o * 41.0

def norm(v):
    out = {}
    for d, trs in v.items():
        s = vol14.loc[d]
        if not np.isfinite(s):
            continue
        f = 25000.0 / lvl.loc[d] * min(2.0, 0.012 / s)
        out[d] = [dict(pnl_pts=t["pnl_pts"] * f, mae_pts=t["mae_pts"] * f, risk_pts=t["risk_pts"] * f) for t in trs]
    return out

V = {"base (Swing)": noise_momentum(q),
     "Std: skip 10:00+14:00": noise_momentum(q, shift=("10:00", "14:00")),
     "Std: skip 10:00+14:00+14:30": noise_momentum(q, shift=("10:00", "14:00", "14:30"))}
V = {k: norm(v) for k, v in V.items()}
pickle.dump(V, open(P + "trades_std.pkl", "wb"))

for k, v in V.items():
    ds = sorted(v); days = [v[d] for d in ds]
    d = pd.Series([sum(t["pnl_pts"] for t in x) * 2 for x in days], index=pd.to_datetime(ds))
    yr = d.groupby(d.index.year).sum().round(-1)
    print(f"\n#### {k}: per MNQ ${d.mean():.1f}/day, Sharpe {d.mean()/d.std()*252**.5:.2f}, years>0 {(yr>0).sum()}/{len(yr)}")
    print("   $/yr per MNQ:", yr.astype(int).to_dict())
    for dpp in (5, 8):
        f = [ftmo_funded(days, s, dpp) for s in range(0, len(days) - 252, 5)]
        print(f"   funded 2-Step @${dpp}/pt: avg paid ${np.mean([x[0] for x in f]):,.0f}/yr, breach {100*np.mean([x[1]=='breach' for x in f]):.0f}%")

# speed: eval (no news restriction in evaluation -> base trades)
v = V["base (Swing)"]; ds = sorted(v); days = [v[d] for d in ds]
print("\n#### Speed vs pass rate (evaluation, no news rule)")
for dpp in (8, 10, 12, 15):
    o = [ftmo2(days, s, dpp) for s in range(0, len(days) - 300, 2)]
    md = np.median([x[1] for x in o if x[0] == "pass"])
    print(f"   2-Step @${dpp}/pt: {summarize(o)} median days {md:.0f}")
for dpp in (5, 6, 8, 10):
    o = [ftmo1(days, s, dpp) for s in range(0, len(days) - 300, 2)]
    md = np.median([x[1] for x in o if x[0] == "pass"])
    print(f"   1-Step @${dpp}/pt: {summarize(o)} median days {md:.0f}")
