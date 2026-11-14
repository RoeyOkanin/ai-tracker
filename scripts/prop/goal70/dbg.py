from sim import *
import datetime as dt
new = build("b12_14")
dates = [d for d, _ in new]
s = next(i for i, d in enumerate(dates) if d >= dt.date(2025, 1, 2))
X = 12; bal = 0; prev = None
for k in range(s, s + 120):
    d, trs = new[k]
    skip = prev is not None and prev > 167 * X
    day = 0 if skip else sum(X * t[0] for t in trs)
    low = min([0] + [X * t[1] for t in trs]) if not skip else 0
    bal += day; prev = 0 if skip else day
    if abs(day) > 1500 or skip or k % 10 == 0:
        print(d, "skip" if skip else "", round(day), "low", round(low), "bal", round(bal), "vs", round(min(2, 0.012 / D.vol14[d]), 2))
print(attempt(new, s, fixed(12)))
