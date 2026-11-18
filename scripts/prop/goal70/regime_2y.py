"""Has the US100 intraday regime changed in 2024-26 vs 2016-23, in ways that matter for the noise-band EA?
Market metrics per year from QQQ 5-min RTH bars + EA v2 trade stats ($10/pt, cost 5, vol cap 1,
x1.5 below MA50, no entries 12:00/14:00, skip after a win > $1,670)."""
import contextlib, io, numpy as np, pandas as pd
with contextlib.redirect_stdout(io.StringIO()):
    import funded_life as F
from sim import R, D
from gen_trades import S, prep

q = S.load("../../../data/prop/QQQ_5m.csv.gz")
days_all, g = prep(q)
X, SKIP = 10.0, 1670.0

# ---------- market metrics per day ----------
rows = []
prev_c = None
for d in days_all:
    x = g[d]
    if len(x) < 70:
        prev_c = x.close.iloc[-1]; continue
    o, c, h, l = x.open.iloc[0], x.close.iloc[-1], x.high.max(), x.low.min()
    r5 = np.diff(np.log(np.r_[o, x.close.values]))
    rv = np.sqrt((r5 ** 2).sum())                      # intraday realized vol (open->close)
    # 30-min returns (13 half hours)
    c30 = x.close.resample("30min", label="right", closed="left").last().dropna().values
    r30 = np.diff(np.log(np.r_[o, c30]))
    ac30 = np.corrcoef(r30[:-1], r30[1:])[0, 1] if len(r30) > 5 else np.nan
    # variance ratio: (open->close var) / sum of 30m vars  (>1 trending, <1 mean-reverting)
    vr = (np.log(c / o) ** 2) / (r30 ** 2).sum() if (r30 ** 2).sum() > 0 else np.nan
    t = x.index
    m10 = x.close[t.hour * 60 + t.minute < 600].iloc[-1]          # 10:00 close
    m1530 = x.close[t.hour * 60 + t.minute < 930].iloc[-1]        # 15:30
    rows.append(dict(d=d, year=d.year, o=o, c=c, h=h, l=l,
                     gap=abs(o / prev_c - 1) if prev_c else np.nan,
                     o2c=abs(c / o - 1), rng=(h - l) / o, rv=rv,
                     eff=abs(c - o) / (h - l) if h > l else np.nan,
                     ac30=ac30, vr=vr,
                     early=np.log(m10 / o), mid=np.log(m1530 / m10), late=np.log(c / m1530)))
    prev_c = c
M = pd.DataFrame(rows).set_index("d")
M["c2c"] = np.log(M.c / M.c.shift(1)).abs()
M["gap_share"] = M.gap / (M.gap + M.o2c)
# trend day: efficiency > 0.6 and range above its trailing 60d median
M["trend"] = (M.eff > 0.6) & (M.rng > M.rng.rolling(60).median().shift(1))

# ---------- EA trades per day ($) ----------
raw = R["b12_14"]
er = []
prev = None
for (d, trs) in F.days:
    pnl = [X * t[0] for t in trs]
    skipped = prev is not None and prev > SKIP
    if skipped:
        prev = 0.0; continue
    rt = raw.get(d, [])
    vs = min(1.0, 0.012 / D.vol14[d])
    for p, t in zip(pnl, rt):
        er.append(dict(d=d, year=d.year, pnl=p, eod=t["eod"], vs=vs))
    prev = sum(pnl)
T = pd.DataFrame(er)

def ea_stats(t):
    w, lo = t[t.pnl > 0], t[t.pnl <= 0]
    return dict(n=len(t), win=len(w) / len(t), avgW=w.pnl.mean(), avgL=lo.pnl.mean(),
                PF=w.pnl.sum() / -lo.pnl.sum(), pnl=t.pnl.sum(),
                whip=(~t.eod & (t.pnl <= 0)).mean(),          # stopped-out losers share
                big=(t.pnl > 3000).sum(), bigsum=t[t.pnl > 3000].pnl.sum())

pd.set_option("display.width", 200)
pd.set_option("display.float_format", lambda v: f"{v:,.3f}")
print("=== market by year (daily %, medians unless noted) ===")
yr = M.groupby("year").agg(rv=("rv", lambda s: s.mean() * 100), c2c=("c2c", lambda s: s.mean() * 100),
                           gap=("gap", lambda s: s.mean() * 100), gapshare=("gap_share", "mean"),
                           o2c=("o2c", lambda s: s.mean() * 100), eff=("eff", "mean"),
                           trend=("trend", "mean"), ac30=("ac30", "mean"), vr=("vr", "mean"))
# late-day momentum: corr(early+mid, late) by year
yr["late_mom"] = M.groupby("year").apply(lambda s: np.corrcoef(s.early + s.mid, s.late)[0, 1])
print(yr)

print("\n=== EA v2 by year ($10/pt) ===")
E = pd.DataFrame({y: ea_stats(t) for y, t in T.groupby("year")}).T
print(E)

def per(mask_m, mask_t, name):
    m = M[mask_m]; t = T[mask_t]
    s = ea_stats(t)
    yrs = len(m) / 252
    print(f"{name:10s} rv {m.rv.mean()*100:.2f}% gap {m.gap.mean()*100:.2f}% gapshare {m.gap_share.mean():.2f} "
          f"eff {m.eff.mean():.3f} trend {m.trend.mean():.1%} ac30 {m.ac30.mean():+.3f} vr {m.vr.mean():.2f} "
          f"late_mom {np.corrcoef(m.early+m.mid, m.late)[0,1]:+.3f} | EA $/yr {s['pnl']/yrs:,.0f} PF {s['PF']:.2f} "
          f"win {s['win']:.0%} avgW {s['avgW']:,.0f} avgL {s['avgL']:,.0f} whip {s['whip']:.0%} trades/yr {s['n']/yrs:.0f}")

print("\n=== periods ===")
dm = pd.to_datetime(M.index); dt = pd.to_datetime(T.d)
per(dm < "2024-01-01", dt < "2024-01-01", "2016-23")
per(dm >= "2024-01-01", dt >= "2024-01-01", "2024-26")
per(dm >= "2025-11-01", dt >= "2025-11-01", "last 12m")
per(dm >= "2026-05-01", dt >= "2026-05-01", "last 6m")

# bootstrap: how unusual is the last-24m EA result vs random 24m windows in 2016-23?
daily = T.groupby("d").pnl.sum().reindex(pd.Index(F.days and [d for d, _ in F.days]), fill_value=0.0)
daily.index = pd.to_datetime(daily.index)
w = 504
roll = daily.rolling(w).sum().dropna()
last = roll.iloc[-1]
hist = roll[roll.index < "2024-01-01"]
print(f"\nlast 24m EA P&L ${last:,.0f}; 2016-23 rolling-24m windows: median ${hist.median():,.0f}, "
      f"5th pct ${hist.quantile(.05):,.0f}, share below last {(hist < last).mean():.0%}")
r12 = daily.rolling(252).sum().dropna()
print(f"last 12m ${r12.iloc[-1]:,.0f}; 2016-23 rolling-12m: median ${r12[r12.index<'2024-01-01'].median():,.0f}, "
      f"share below last {(r12[r12.index<'2024-01-01'] < r12.iloc[-1]).mean():.0%}")
# rolling 12m P&L at each year end
print("rolling 12m P&L by quarter-end:")
print(r12.resample("QE").last().tail(16).map(lambda v: f"{v:,.0f}").to_string())
T.to_pickle("/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/regime_T.pkl")
M.to_pickle("/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/regime_M.pkl")
