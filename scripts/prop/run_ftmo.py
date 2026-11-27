import pickle, numpy as np
from propsim import ftmo2, ftmo_funded, summarize
res = pickle.load(open("/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/trades_norm.pkl", "rb"))
ds = sorted(res["noise_vwap"]); days = [res["noise_vwap"][d] for d in ds]
print("FTMO 2-Step $100k, US100 CFD, noise momentum, $ per NQ point (20 = 1 NQ)")
for dpp in (20, 40, 60, 80, 100):
    o = [ftmo2(days, s, dpp) for s in range(0, len(days) - 300, 2)]
    f = [ftmo_funded(days, s, dpp) for s in range(0, len(days) - 252, 5)]
    print(dpp, summarize(o), f"| funded 1y: avg paid ${np.mean([x[0] for x in f]):,.0f}, breach {100*np.mean([x[1]=='breach' for x in f]):.0f}%")
