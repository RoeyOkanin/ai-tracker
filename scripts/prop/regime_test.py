"""Roey's ideas (14.11): (1) pause after a big win, (2) find what big trend days share and trade only those.
Discovery 2016-2021, validation 2022-2026. Daily P&L at $12/pt, cost 5 pts/trade (live-calibrated)."""
import pickle, numpy as np, pandas as pd, datetime as dt
from strategies import load
P = "/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/"
v = pickle.load(open(P + "trades_norm.pkl", "rb"))["noise_vwap_vt"]
q = load("../../data/prop/QQQ_5m.csv.gz")
g = q.groupby("date")
D = pd.DataFrame(dict(o=g.open.first(), c=g.close.last(), h=g.high.max(), l=g.low.min()))
D["ret"] = D.c.pct_change()
D["gap"] = (D.o / D.c.shift(1) - 1).abs()
D["vol14"] = D.ret.rolling(14).std().shift(1)
D["vol_ratio"] = D.ret.abs().rolling(5).mean().shift(1) / D.vol14          # recent 5d vs 14d
D["prev_range"] = ((D.h - D.l) / D.o).shift(1) / D.vol14
D["trend20"] = (D.c.shift(1) / D.c.shift(21) - 1) / (D.vol14 * np.sqrt(20))  # 20d trend in sd
D["dow"] = pd.to_datetime(D.index).dayofweek
pnl = pd.Series({d: sum((t["pnl_pts"] - 5.0) * 12 for t in v[d]) for d in v})
D = D.join(pnl.rename("pnl"), how="inner")
D["prev_pnl"] = D.pnl.shift(1)
D["prev5_pnl"] = D.pnl.rolling(5).sum().shift(1)
D["era"] = np.where(pd.to_datetime(D.index) < "2022-01-01", "disc", "valid")
def stats(s):
    e = s.cumsum(); return f"n={len(s):4d} sum={s.sum():9,.0f} per-day={s.mean():6.0f} sharpe={s.mean()/s.std()*np.sqrt(252):5.2f} maxDD={(e-e.cummax()).min():9,.0f}"
for era in ("disc", "valid"):
    print(era, "ALL      ", stats(D.pnl[D.era == era]))
print("\n(1) pause N days after a day with pnl > X")
for X in (2000, 4000, 6000):
    for N in (1, 3, 5):
        m = pd.Series(False, index=D.index); idx = list(D.index)
        for i, d in enumerate(idx):
            if D.pnl.iloc[i] > X:
                for j in range(i + 1, min(i + 1 + N, len(idx))): m.iloc[j] = True
        for era in ("disc", "valid"):
            s = D.pnl[(D.era == era)]; skip = s[m[D.era == era]]
            print(f"  X={X} N={N} {era}: skipped {len(skip):3d} days worth {skip.sum():8,.0f} -> {stats(s[~m[D.era == era]])}")
print("\n(2) quintiles of features: avg daily pnl per quintile (disc | valid)")
for f in ["gap", "vol14", "vol_ratio", "prev_range", "trend20", "prev_pnl", "prev5_pnl", "dow"]:
    row = []
    for era in ("disc", "valid"):
        x = D[D.era == era]
        b = x[f] if f == "dow" else pd.qcut(x[f], 5, labels=False, duplicates="drop")
        row.append(" ".join(f"{m:5.0f}" for m in x.groupby(b).pnl.mean()))
    print(f"  {f:10s} disc [{row[0]}] | valid [{row[1]}]")

print("\n(3) robustness of 'skip the day after a big win' (N=1), by threshold, and by year for X=2000")
idx = list(D.index)
def skipmask(cond):
    m = cond.shift(1, fill_value=False).astype(bool); return m
for X in (1000, 1500, 2000, 2500, 3000):
    m = skipmask(D.pnl > X)
    print(f"  X={X}: " + " | ".join(f"{era} skipped {m[D.era==era].sum():3d} worth {D.pnl[m & (D.era==era)].sum():8,.0f}" for era in ("disc", "valid")))
m = skipmask(D.pnl > 2000)
yr = pd.to_datetime(D.index).year
print("  per year, pnl on skipped days:", dict((int(y), int(D.pnl[m & (yr == y)].sum())) for y in sorted(set(yr))))
print("\n(4) market-based version: skip the day after |QQQ return| > k * vol14 (strategy-independent)")
for k in (1.5, 2.0, 2.5):
    m2 = skipmask(D.ret.abs() > k * D.vol14)
    print(f"  k={k}: " + " | ".join(f"{era} skipped {m2[D.era==era].sum():3d} worth {D.pnl[m2 & (D.era==era)].sum():8,.0f}" for era in ("disc", "valid")))
print("\n(5) skip after a big LOSS day (control)")
for X in (1000, 2000):
    m3 = skipmask(D.pnl < -X)
    print(f"  X={X}: " + " | ".join(f"{era} skipped {m3[D.era==era].sum():3d} worth {D.pnl[m3 & (D.era==era)].sum():8,.0f}" for era in ("disc", "valid")))
