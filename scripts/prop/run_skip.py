"""FTMO plan with 'skip the day after a big win' (yesterday's strategy P&L > TH normalized points, cost 5)."""
import pickle, numpy as np
from propsim import ftmo2, ftmo_funded_dyn
P = "/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/"
v = pickle.load(open(P + "trades_norm.pkl", "rb"))[__import__("os").environ.get("KEY","noise_vwap_vt")]
ds = sorted(v); base = [v[d] for d in ds]; C = 5.0; FEE = 590
def skipped(th):
    out = [base[0]]
    for i in range(1, len(ds)):
        y = sum(t["pnl_pts"] - C for t in base[i - 1])
        out.append([] if y > th else base[i])
    return out
for th in (None, 167):
    days = base if th is None else skipped(th)
    for ev in (12,):
        tot, got_at, res = [], [], []
        for s in range(0, len(ds) - 260, 3):
            r0, _ = ftmo2(days, s, ev, cost_pts=C, max_tdays=500); res.append(r0)
            t, paid, cost, got = 0, 0.0, 0, None
            while t < 252:
                cost += FEE
                r, k = ftmo2(days, s + t, ev, cost_pts=C, max_tdays=252 - t); t += k
                if r == "pass":
                    got = t; p, _ = ftmo_funded_dyn(days, s + t, 6, cost_pts=C, horizon=252 - t, power=1)
                    paid += p + (FEE if p > 0 else 0); break
                if r != "fail": break
            tot.append(paid - cost); got_at.append(got)
        f = [x for x in got_at if x is not None]
        fr = [ftmo_funded_dyn(days, s, fd, cost_pts=C, horizon=252, power=1) for s in range(0, len(ds) - 252, 5) for fd in (6,)]
        print(f"skip>{th}: eval$12 single pass {100*np.mean([x=='pass' for x in res]):.0f}% | funded<12m {100*len(f)/len(got_at):.0f}% median day {np.median(f):.0f} | yr1 net ${np.mean(tot):,.0f} P(loss) {100*np.mean([x<0 for x in tot]):.0f}% | funded $6 yr ${np.mean([x[0] for x in fr]):,.0f} breach {100*np.mean([x[1]=='breach' for x in fr]):.0f}%", flush=True)
