"""Can failed-breakout (chop) days be avoided or faded? Tests on EA v2 trades ($10, cost 5), split 2016-21 / 2022-26."""
import contextlib, io, numpy as np, pandas as pd
with contextlib.redirect_stdout(io.StringIO()):
    import funded_life as F
from sim import R, D
from gen_trades import S, prep, K
q = S.load("../../../data/prop/QQQ_5m.csv.gz"); days_all, g = prep(q)
X = 10.0
raw = R["b12_14"]
def bar_close(d, m):  # close of the bar ending at minute m
    x = g[d]; sm = x.index.hour * 60 + x.index.minute + 5
    i = np.searchsorted(sm, m); i = min(i, len(x) - 1); return x.close.values[i]
rows = []
for (d, trs) in F.days:
    vs = min(1.0, 0.012 / D.vol14[d]); n = 25000 / D.lvl[d]; tilt = F.TILT.get(d, 1.0)
    rt = raw.get(d, [])
    pnl = [X * t[0] for t in trs]
    # fade: after a losing non-EOD exit, take the opposite side until the close (cost 5 too)
    fade = 0.0
    for t, p in zip(rt, pnl):
        if p < 0 and not t["eod"]:
            px = bar_close(d, t["xt"]); pc = g[d].close.values[-1]
            fade += X * tilt * (vs * n * (-t["side"]) * (pc - px) * K - 5 * vs)
    gap = abs(D.o[d] / D.c.shift(1)[d] - 1)
    rows.append(dict(d=d, pnl=pnl, fade=fade, gap=gap, vol=D.vol14[d]))
T = pd.DataFrame(rows); T["d"] = pd.to_datetime(T.d); T["base"] = T.pnl.apply(sum)
def stop_after(p, k):
    out, losses = 0.0, 0
    for v in p:
        if losses >= k: break
        out += v; losses += v < 0
    return out
for k in (1, 2): T[f"stop{k}"] = T.pnl.apply(lambda p: stop_after(p, k))
T["first_only_loss"] = T.pnl.apply(lambda p: p[0] if p else 0)
A_, B_ = T.d < "2022-01-01", T.d >= "2022-01-01"
def rep(name, s):
    print(f"{name:42s} 2016-21 ${s[A_].sum()/6:8,.0f}/yr   2022-26 ${s[B_].sum()/4.87:8,.0f}/yr   maxDD ${(s.cumsum()-s.cumsum().cummax()).min():9,.0f}")
rep("base (EA v2)", T.base)
rep("stop for the day after 1 loss", T.stop1)
rep("stop for the day after 2 losses", T.stop2)
rep("base + fade every failed breakout to close", T.base + T.fade)
rep("fade alone", T.fade)
# skip days by gap size / vol quintile (thresholds from first half only)
for col in ("gap", "vol"):
    qs = T[A_][col].quantile([.2, .4, .6, .8]).values
    T["b"] = np.digitize(T[col], qs)
    print(col, "quintile P&L/day 2016-21:", [round(T[A_ & (T.b == i)].base.mean()) for i in range(5)],
          " 2022-26:", [round(T[B_ & (T.b == i)].base.mean()) for i in range(5)])
# after N losing days in a row
T["lost"] = T.base < 0
for n in (2, 3):
    streak = T.lost.rolling(n).sum().shift(1) == n
    print(f"after {n} losing days: next-day avg 2016-21 ${T[A_ & streak].base.mean():.0f} (n {int((A_&streak).sum())}), 2022-26 ${T[B_ & streak].base.mean():.0f} (n {int((B_&streak).sum())}); all days avg ${T.base.mean():.0f}")
