import sim
from sim import *
import datetime as dt
Dd = D.copy(); below50 = Dd.c.shift(1) < Dd.c.rolling(50).mean().shift(1)
days = build_mult(build("b12_14", cap=1.0), {d: (1.5 if v else 1.0) for d, v in below50.items()})
src = open("sim.py").read()
for buf in (0.005, 0.003, 0.002, 0.001):
    code = src.replace("lim_floor = (-0.10 * A + 0.005 * A) - bal", f"lim_floor = (-0.10 * A + {buf} * A) - bal")
    ns = {}; exec(compile(code, "simb", "exec"), ns)
    o, df = ns["evaluate"](days, ns["fixed"](10), target_stop=True)
    s = next(i for i, (d, _) in enumerate(days) if d >= dt.date(2026, 1, 2))
    print(f"floor guard buffer {buf*100:.1f}%: 12m {o['all']['p12']}% 24m {o['all']['p24']}% (A {o['A']['p12']} B {o['B']['p12']}) | start 2026-01-02: {ns['attempt'](days, s, ns['fixed'](10), target_stop=True)}")
