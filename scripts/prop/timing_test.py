"""Are there entry times / days to eliminate? Trade-level, cost 5 pts, $12/pt, vol-scaled. Halves: 2016-21 / 2022-26."""
import numpy as np, pandas as pd, datetime as dt
import strategies as S
q = S.load("../../data/prop/QQQ_5m.csv.gz")
D = q.groupby("date").agg(o=("open", "first"), c=("close", "last"))
vol = D.c.pct_change().rolling(14).std().shift(1)
src = open("strategies.py").read()
src = src.replace("trades.append(dict(pnl_pts=pos * (b.close - entry) * NQ_PER_QQQ,", "trades.append(dict(et=et, pnl_pts=pos * (b.close - entry) * NQ_PER_QQQ,")
src = src.replace("pos, entry, mae = 1, b.close, 0.0", "pos, entry, mae, et = 1, b.close, 0.0, ts").replace("pos, entry, mae = -1, b.close, 0.0", "pos, entry, mae, et = -1, b.close, 0.0, ts")
src = src.replace("trades.append(dict(pnl_pts=pos * (x.close.iloc[-1] - entry)", "trades.append(dict(et=et, pnl_pts=pos * (x.close.iloc[-1] - entry)")
ns = {}; exec(compile(src, "s", "exec"), ns)
tr = ns["noise_momentum"](q)
rows = []
for d, ts in tr.items():
    s = vol.get(d)
    if s is None or not np.isfinite(s): continue
    f = 25000 / (D.o[d] * 41) * min(2, 0.012 / s)
    for t in ts:
        rows.append(dict(d=d, hm=(t["et"] + pd.Timedelta(minutes=5)).strftime("%H:%M"), pnl=(t["pnl_pts"] * f - 5 * min(2, 0.012 / s)) * 12))
T = pd.DataFrame(rows); T["era"] = np.where(pd.to_datetime(T.d) < "2022-01-01", "2016-21", "2022-26")
dd = pd.to_datetime(T.d)
T["dow"] = dd.dt.day_name().str[:3]
T["opex"] = (dd.dt.weekday == 4) & (dd.dt.day.between(15, 21))
bd = pd.Series(sorted(set(T.d)))
T["month_end"] = T.d.isin(set(bd[pd.to_datetime(bd).dt.month != pd.to_datetime(bd.shift(-1)).dt.month]))
T["month_start"] = T.d.isin(set(bd[pd.to_datetime(bd).dt.month != pd.to_datetime(bd.shift(1)).dt.month]))
pd.set_option("display.width", 200)
for col in ["hm", "dow", "opex", "month_end", "month_start"]:
    print(f"\n== {col}: total $ (trades)")
    print(T.pivot_table(index=col, columns="era", values="pnl", aggfunc=["sum", "count"]).round(0))
