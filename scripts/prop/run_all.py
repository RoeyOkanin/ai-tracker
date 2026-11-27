import pickle, numpy as np
from propsim import apex_eval, apex_pa, ftmo2, ftmo_funded, summarize
res = pickle.load(open("/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/trades_norm.pkl", "rb"))
for key in ("noise_vwap", "noise_vwap_vt", "orb5_EOD_vt"):
    ds = sorted(res[key]); days = [res[key][d] for d in ds]
    print(f"\n##### {key}  ({ds[0]} .. {ds[-1]}, {len(ds)} days)")
    print("APEX 50K EOD eval:")
    grid = [dict(fixed=n) for n in (3, 4, 5, 6, 8, 10)] if "noise" in key else [dict(risk_usd=r) for r in (200, 300, 400)]
    for kw in grid:
        print("  ", kw, summarize([apex_eval(days, s, **kw) for s in range(len(days) - 21)]))
    print("APEX 50K PA (1y horizon):")
    for kw in (grid[:4] if "noise" in key else grid):
        o = [apex_pa(days, s, **kw) for s in range(0, len(days) - 252, 3)]
        tot = [sum(x["payouts"]) for x in o]; npay = [len(x["payouts"]) for x in o]
        print(f"   {kw} avg paid ${np.mean(tot):,.0f} | median ${np.median(tot):,.0f} | >=1 payout {100*np.mean([k>0 for k in npay]):.0f}% | breach {100*np.mean([x['result']=='breach' for x in o]):.0f}% | all 6 {100*np.mean([x['result']=='maxed' for x in o]):.0f}%")
    if "noise" in key:
        print("FTMO 2-Step 100k US100 ($/pt; 20 = 1 NQ):")
        for dpp in (5, 8, 10, 15, 20):
            o = [ftmo2(days, s, dpp) for s in range(0, len(days) - 300, 2)]
            f = [ftmo_funded(days, s, dpp) for s in range(0, len(days) - 252, 5)]
            print("  ", dpp, summarize(o), f"| funded 1y: avg paid ${np.mean([x[0] for x in f]):,.0f}, breach {100*np.mean([x[1]=='breach' for x in f]):.0f}%")
