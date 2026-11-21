import pickle, numpy as np
from propsim import ftmo2_dyn, ftmo_funded_dyn, summarize
P = "/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/"
v = pickle.load(open(P + "trades_norm.pkl", "rb"))["noise_vwap_vt"]
ds = sorted(v); days = [v[d] for d in ds]
half = len(days) // 2
for power, ds_ in [(0, None), (1, None), (2, None), (0, 0.02), (1, 0.02), (1, 0.03), (2, 0.02)]:
    line = f"power {power} daystop {ds_}:"
    for dpp in (10, 12, 15):
        o = [ftmo2_dyn(days, s, dpp, power=power, day_stop_pct=ds_) for s in range(0, len(days) - 300, 2)]
        p = [x for x in o if x[0] == "pass"]
        line += f" | ${dpp}: pass {100*len(p)/len(o):.0f}% med {np.median([x[1] for x in p]):.0f}d"
    for dpp in (5, 7):
        f = [ftmo_funded_dyn(days, s, dpp, power=power, day_stop_pct=ds_) for s in range(0, len(days) - 252, 5)]
        line += f" | funded ${dpp}: ${np.mean([x[0] for x in f])/1000:.1f}k br {100*np.mean([x[1]=='breach' for x in f]):.0f}%"
    print(line, flush=True)
