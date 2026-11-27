"""12-month money from one FTMO 2-Step 100K Swing: eval at $X/pt static, then funded with
buffer-scaled sizing (size x distance-to-floor/10%, min 25%). Retries on fail. Compares to the old plan."""
import pickle, numpy as np
from propsim import ftmo2, ftmo_funded_dyn
P = "/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/"
v = pickle.load(open(P + "trades_norm.pkl", "rb"))["noise_vwap_vt"]
ds = sorted(v); days = [v[d] for d in ds]
FEE = 590
for ev, fd, pw, lab in [(12, 5, 0, "old: eval $12, funded $5 fixed"), (12, 8, 1, "new: eval $12, funded $8 buffer-scaled"),
                        (15, 8, 1, "new: eval $15, funded $8 buffer-scaled")]:
    tot, got_at = [], []
    for s in range(0, len(ds) - 260, 3):
        t, paid, cost, got = 0, 0.0, 0, None
        while t < 252:
            cost += FEE
            r, k = ftmo2(days, s + t, ev, max_tdays=252 - t)
            t += k
            if r == "pass":
                got = t
                p, _ = ftmo_funded_dyn(days, s + t, fd, horizon=252 - t, power=pw)
                paid += p + (FEE if p > 0 else 0)
                break
            if r != "fail":
                break
        tot.append(paid - cost); got_at.append(got)
    f = [x for x in got_at if x is not None]
    print(f"{lab}: funded<12m {100*len(f)/len(got_at):.0f}% (median day {np.median(f):.0f}) | year-1 net avg ${np.mean(tot):,.0f} median ${np.median(tot):,.0f} P(loss) {100*np.mean([x<0 for x in tot]):.0f}%")
