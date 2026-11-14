"""Funded-account lifetime under different withdrawal rules (EA v2 funded settings: $8/pt, buffer scaling,
target off, guards, skip-after-win). FTMO: 10% static max loss from the initial 100k, 80% split,
payout requests every 14 days (~10 trading days). Breach = equity reaches the EA floor guard (90.5k)."""
from sim import *
Dd = D.copy(); below50 = Dd.c.shift(1) < Dd.c.rolling(50).mean().shift(1)
TILT = {d: (1.5 if v else 1.0) for d, v in below50.items()}


def make_days(cost=5.0):
    return build_mult(build("b12_14", cap=1.0, cost=cost), TILT)


days = make_days()
YEAR = 252


def life(start, X=8.0, trigger=0.0, keep=0.0, horizon=3 * YEAR, split=0.8, buffer=True, skip_th=167.0, days=days):
    """trigger: request a payout only if profit >= trigger; keep: profit left in the account after a payout
    (0 = FTMO full reset to 100k). Returns (lifetime_days or None if alive, paid_to_trader, paid_by_year)."""
    bal, paid, prev, by_year = 0.0, 0.0, None, [0.0, 0.0, 0.0]
    global LOW
    LOW = 0.0
    for i in range(horizon):
        k = start + i
        if k >= len(days):
            return None, paid, by_year, i
        d, trs = days[k]
        s = min(1.0, max(0.25, (bal + 0.10 * A) / (0.10 * A))) if buffer else 1.0
        x = X * s
        if not (skip_th and prev is not None and prev > skip_th * x):
            cur, hit = 0.0, False
            lim_floor = (-0.10 * A + 0.005 * A) - bal
            lim = max(-0.045 * A, lim_floor)
            for (pu, mu, fu, et, side) in trs:
                LOW = min(LOW, bal + cur + x * mu)
                if cur + x * mu <= lim:
                    cur = lim; hit = lim == lim_floor
                    break
                cur += x * pu
            if hit:
                return i + 1, paid, by_year, i + 1
            bal += cur; prev = cur
        else:
            prev = 0.0
        if i >= 10 and i % 10 == 0 and bal >= max(trigger, 1.0) and bal > keep:
            w = bal - keep
            paid += split * w; by_year[min(2, i // YEAR)] += split * w
            bal = keep
    return None, paid, by_year, horizon


rules = [("withdraw everything every 2 weeks (FTMO default)", 0, 0),
         ("withdraw everything only when >= 105K", 5000, 0),
         ("withdraw everything only when >= 108K", 8000, 0),
         ("keep a 5K cushion, withdraw above 105K", 5000, 5000),
         ("keep an 8K cushion, withdraw above 108K", 8000, 8000)]
starts = [s for s in range(0, len(days)) if len(days) - s >= 3 * YEAR][::3]
print(f"starts: {len(starts)} from {days[starts[0]][0]} to {days[starts[-1]][0]} (each followed for up to 3 years)")
for name, trig, keep in rules:
    R_ = [life(s, trigger=trig, keep=keep) for s in starts]
    lt = np.array([r[0] if r[0] is not None else 10**9 for r in R_])
    paid = np.array([r[1] for r in R_])
    y1 = np.array([r[2][0] for r in R_])
    alive = [100 * np.mean(lt > n * YEAR) for n in (1, 2, 3)]
    burned = lt[lt < 10**9]
    med_burn = np.median(burned) / 21 if len(burned) else float("nan")
    # paid per account until it burns (or 3 years), and per year alive
    yrs_alive = np.minimum(lt, 3 * YEAR) / YEAR
    print(f"{name:42s} alive 1y {alive[0]:5.1f}% 2y {alive[1]:5.1f}% 3y {alive[2]:5.1f}% | burned within 3y: {100*len(burned)/len(lt):5.1f}% "
          f"(median {med_burn:4.1f} months) | to Roey: year-1 median ${np.median(y1):,.0f} avg ${y1.mean():,.0f}; "
          f"3y/lifetime median ${np.median(paid):,.0f} avg ${paid.mean():,.0f}; per year alive ${paid.sum()/yrs_alive.sum():,.0f}", flush=True)

# ---- closest call and edge-decay stress (recommended rule: withdraw everything only when >= 105K) ----
def run(dd, trig, keep):
    out = []
    for s in starts:
        r = life(s, trigger=trig, keep=keep, days=dd)
        out.append((r[0], r[1], LOW))
    lt = np.array([o[0] if o[0] is not None else 10**9 for o in out]); paid = np.array([o[1] for o in out])
    low = np.array([o[2] for o in out])
    yrs = np.minimum(lt, 3 * YEAR) / YEAR
    return lt, paid, low, yrs


base_mean = np.mean([pu for _, trs in days for (pu, *_r) in trs])
print("\nedge-decay stress (extra cost per trade = weaker edge), rule: withdraw everything only when >= 105K")
for extra in (0, 2, 4, 6, 8):
    dd = days if extra == 0 else make_days(5.0 + extra)
    m = np.mean([pu for _, trs in dd for (pu, *_r) in trs])
    lt, paid, low, yrs = run(dd, 5000, 0)
    burned = lt < 10**9
    print(f"extra cost {extra} pts: edge {100*m/base_mean:5.1f}% of base | burned within 1y {100*np.mean(lt <= YEAR):5.1f}% "
          f"within 3y {100*burned.mean():5.1f}% (median {np.median(lt[burned])/21 if burned.any() else float('nan'):4.1f} months) | "
          f"lowest equity: worst ${A+low.min():,.0f}, 5th pct ${A+np.percentile(low,5):,.0f}, median ${A+np.median(low):,.0f} | "
          f"to Roey per year alive ${paid.sum()/yrs.sum():,.0f}", flush=True)
