"""Money in the first 12 months from buying one FTMO 2-Step 100K: evaluation at size X (base trades,
no news rule in evaluation), then funded Standard at $5/pt with 10:00/14:00 checkpoints shifted.
A failed attempt is retried immediately (new fee) until the 12 months run out."""
import pickle, numpy as np
from propsim import ftmo2, ftmo_funded
P = "/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/"
V = pickle.load(open(P + "trades_std.pkl", "rb"))
b = V["base (Swing)"]; s_ = V["Std: skip 10:00+14:00"]
ds = sorted(set(b) & set(s_)); eb = [b[d] for d in ds]; es = [s_[d] for d in ds]
FEE = 590  # ~EUR 540 in USD
for dpp in (8, 10, 12, 15):
    tot, fees, funded_at = [], [], []
    for s in range(0, len(ds) - 260, 3):
        t, paid, cost, got = 0, 0.0, 0, None
        while t < 252:
            cost += FEE
            r, k = ftmo2(eb, s + t, dpp, max_tdays=252 - t)
            t += k
            if r == "pass":
                got = t
                p, _ = ftmo_funded(es, s + t, 5, horizon=252 - t)
                paid += p + (FEE if p > 0 else 0)  # fee refunded with first reward
                break
            if r != "fail":
                break
        tot.append(paid - cost); fees.append(cost); funded_at.append(got)
    f = [x for x in funded_at if x is not None]
    print(f"eval ${dpp}/pt: funded within 12m {100*len(f)/len(funded_at):.0f}% (median day {np.median(f):.0f}) | "
          f"net 12m avg ${np.mean(tot):,.0f}, median ${np.median(tot):,.0f}, P(loss) {100*np.mean([x<0 for x in tot]):.0f}% | fees avg ${np.mean(fees):,.0f}")
