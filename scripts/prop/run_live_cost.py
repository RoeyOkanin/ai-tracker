"""Re-run the FTMO plan with live-calibrated costs. MT5 tester (2025-11..2026-11, real ticks, after the
DST fix) made +$16.8k where the python backtest made +$26.1k on the same days -> ~3.5 extra pts/trade.
So cost_pts 1.5 (backtest) vs 5.0 (live-calibrated)."""
import pickle, numpy as np
from propsim import ftmo2, ftmo_funded_dyn
P = "/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/"
v = pickle.load(open(P + "trades_norm.pkl", "rb"))["noise_vwap_vt"]
ds = sorted(v); days = [v[d] for d in ds]
FEE = 590
for c in (1.5, 5.0):
    for ev in (6, 8, 10, 12):
        tot, got_at, res = [], [], []
        for s in range(0, len(ds) - 260, 3):
            r0, _ = ftmo2(days, s, ev, cost_pts=c, max_tdays=500); res.append(r0)
            t, paid, cost, got = 0, 0.0, 0, None
            while t < 252:
                cost += FEE
                r, k = ftmo2(days, s + t, ev, cost_pts=c, max_tdays=252 - t)
                t += k
                if r == "pass":
                    got = t
                    p, _ = ftmo_funded_dyn(days, s + t, 8, cost_pts=c, horizon=252 - t, power=1)
                    paid += p + (FEE if p > 0 else 0)
                    break
                if r != "fail":
                    break
            tot.append(paid - cost); got_at.append(got)
        f = [x for x in got_at if x is not None]
        print(f"cost {c} eval ${ev}/pt: single attempt pass {100*np.mean([x=='pass' for x in res]):.0f}% | funded<12m {100*len(f)/len(got_at):.0f}% (median day {np.median(f) if f else 0:.0f}) | year-1 net avg ${np.mean(tot):,.0f} P(loss) {100*np.mean([x<0 for x in tot]):.0f}%", flush=True)
