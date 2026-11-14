from sim import *
import datetime as dt
Dd = D.copy(); below50 = Dd.c.shift(1) < Dd.c.rolling(50).mean().shift(1)
days = build_mult(build("b12_14", cap=1.0), {d: (1.5 if v else 1.0) for d, v in below50.items()})
X = 10.0
a, b = dt.date(2026, 1, 1), dt.date(2026, 11, 13)
bal, peak, prev = 0.0, 0.0, None
min_bal, min_eq, max_dd_bal, max_dd_eq = 0.0, 0.0, 0.0, 0.0
n_trades, n_days_traded, skipped, monthly = 0, 0, 0, {}
wins = losses = 0
for d, trs in days:
    if not (a <= d <= b):
        continue
    if prev is not None and prev > 167 * X:
        prev = 0.0; skipped += 1
        continue
    cur, low = 0.0, 0.0
    prev_t = None
    for (pu, mu, fu, et, side) in trs:
        low = min(low, cur + X * mu)
        cur += X * pu
        low = min(low, cur)
    # EA-style trade count: exit+re-entry on the same side and bar is one position (HOLD)
    raw = R["b12_14"][d]
    for i, t in enumerate(raw):
        if i > 0 and raw[i-1]["xt"] == t["et"] and raw[i-1]["side"] == t["side"]:
            continue
        n_trades += 1
    if trs:
        n_days_traded += 1
    eq_low = bal + low
    min_eq = min(min_eq, eq_low)
    max_dd_eq = min(max_dd_eq, eq_low - peak)
    bal += cur
    peak = max(peak, bal)
    min_bal = min(min_bal, bal)
    max_dd_bal = min(max_dd_bal, bal - peak)
    prev = cur
    m = d.strftime("%Y-%m"); monthly[m] = monthly.get(m, 0) + cur
print(f"2026-01-01..2026-11-13 (data ends 13.11 14:15 NY): net {bal:,.0f}  trades(EA-style) {n_trades}  days traded {n_days_traded}  skipped days {skipped}")
print(f"max balance DD {max_dd_bal:,.0f}  max equity DD {max_dd_eq:,.0f}  lowest balance {100000+min_bal:,.0f}  lowest equity {100000+min_eq:,.0f}")
print({k: round(v) for k, v in monthly.items()})
