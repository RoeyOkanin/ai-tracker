import pickle, numpy as np, pandas as pd, sys
from propsim import apex_eval, apex_pa, ftmo_phase, summarize
res = pickle.load(open("/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/trades_norm.pkl", "rb"))

def daylist(v, since=None):
    ds = sorted(v)
    if since: ds = [d for d in ds if str(d) >= since]
    return ds, [v[d] for d in ds]

print("=== APEX 50K EOD eval (target 3000, EOD trail 2000, DLL 1000, 21 trading days) ===")
for k, grid in [("noise_vwap", [("fixed", n) for n in (4, 6, 8, 10, 12, 15, 20)]),
                ("orb5_10R", [("risk", r) for r in (150, 250, 350, 500)]),
                ("orb5_EOD", [("risk", r) for r in (250, 350, 500)])]:
    ds, days = daylist(res[k])
    for mode, x in grid:
        kw = dict(fixed=x) if mode == "fixed" else dict(risk_usd=x)
        out = [apex_eval(days, s, **kw) for s in range(0, len(days) - 21)]
        print(k, mode, x, summarize(out))
