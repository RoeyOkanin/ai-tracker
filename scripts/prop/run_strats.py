import pickle, time, sys
from strategies import load, orb, noise_momentum
q = load("../../data/prop/QQQ_5m.csv.gz")
res = {}
t = time.time()
res["orb5_10R"] = orb(q, 5, 10.0)
res["orb5_EOD"] = orb(q, 5, 1e9)
res["orb15_10R"] = orb(q, 15, 10.0)
res["orb30_10R"] = orb(q, 30, 10.0)
print("orb", time.time() - t, flush=True)
res["noise_vwap"] = noise_momentum(q)
print("noise", time.time() - t, flush=True)
pickle.dump(res, open("/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/trades.pkl", "wb"))
