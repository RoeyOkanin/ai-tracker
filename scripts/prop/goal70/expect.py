from sim import *
import datetime as dt
Dd = D.copy(); below50 = Dd.c.shift(1) < Dd.c.rolling(50).mean().shift(1)
cfgs = {"new EA $10": (build_mult(build("b12_14", cap=1.0), {d: (1.5 if v else 1.0) for d, v in below50.items()}), 10),
        "previous EA $12": (build("b12_14", cap=2.0), 12)}
for name, (days, X) in cfgs.items():
    for a, b in (("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31"), ("2025-11-01", "2026-11-13"), ("2021-11-14", "2026-11-13")):
        a_, b_ = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
        p, prev = [], None
        for d, trs in days:
            if not (a_ <= d <= b_): continue
            if prev is not None and prev > 167 * X:
                p.append(0.0); prev = 0.0; continue
            v = X * sum(t[0] for t in trs); p.append(v); prev = v
        e = np.cumsum(p)
        print(f"{name:16s} {a}..{b}: net {e[-1]:9,.0f}  maxDD {(e-np.maximum.accumulate(e)).min():9,.0f}  min vs start {e.min():9,.0f}")
