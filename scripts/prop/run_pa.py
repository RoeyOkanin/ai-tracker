import pickle, numpy as np, pandas as pd, copy, random
from propsim import apex_eval, apex_pa, summarize
res = pickle.load(open("/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/trades_norm.pkl", "rb"))
ds = sorted(res["noise_vwap"]); days = [res["noise_vwap"][d] for d in ds]

# zero-edge benchmark: same trades, P&L demeaned (removes edge, keeps volatility/path shape)
allp = [t["pnl_pts"] for d in days for t in d]; mu = np.mean(allp)
days0 = [[dict(t, pnl_pts=t["pnl_pts"] - mu, mae_pts=min(t["mae_pts"], t["pnl_pts"] - mu)) for t in d] for d in days]
print("edge per trade pts", round(mu, 2))
for n in ():
    a = summarize([apex_eval(days, s, fixed=n) for s in range(len(days) - 21)])
    b = summarize([apex_eval(days0, s, fixed=n) for s in range(len(days0) - 21)])
    print(f"eval {n} MNQ  real {a}\n            zero-edge {b}")

print("\n=== PA 50K: fixed micros, start every 5th day, up to 1y ===")
for n in (4, 6, 8, 10, 15):
    outs = [apex_pa(days, s, fixed=n) for s in range(0, len(days) - 252, 5)]
    outs0 = [apex_pa(days0, s, fixed=n) for s in range(0, len(days0) - 252, 5)]
    for lab, o in (("real", outs), ("zero", outs0)):
        tot = [sum(x["payouts"]) for x in o]
        npay = [len(x["payouts"]) for x in o]
        print(f"{n:2d} MNQ {lab}: avg paid ${np.mean(tot):,.0f}  >=1 payout {100*np.mean([k>0 for k in npay]):.0f}%  "
              f"breach {100*np.mean([x['result']=='breach' for x in o]):.0f}%  maxed6 {100*np.mean([x['result']=='maxed' for x in o]):.0f}%  avg#pay {np.mean(npay):.2f}")
