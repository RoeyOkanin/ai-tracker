"""FTMO Instant account simulator on the EA v2 US100 trades (cost 5, vol cap 1, x1.5 below MA50, 12/14 blocked).
All money in $ per 100K account (everything scales linearly with account size).
Rules (parameters): daily loss DL% of midnight balance incl. open P&L; max loss ML% trailing on highest closed
balance (optionally locked at the initial balance); payout every 10 trading days if profit since last payout > 0 and
best day <= CONS x period profit; split 90%. EA guards: daily guard g% < DL, floor guard 0.5% above the trailing floor,
optional daily profit cap (close and stop for the day), skip-after-win."""
import sys, contextlib, io, numpy as np
sys.path.insert(0, "../goal70")
with contextlib.redirect_stdout(io.StringIO()):
    import funded_life as F
A, YEAR = 100_000.0, 252


def life(days, start, X, horizon=3 * YEAR, DL=0.03, ML=0.10, lock=True, guard=0.025, cap=None, cons=0.30,
         keep=0.0, split=0.9, buffer=True, skip_th=167.0, every=10):
    bal, hwm, paid, prev = A, A, 0.0, None
    per_start_bal, best_day, period_days = A, 0.0, []
    for i in range(horizon):
        k = start + i
        if k >= len(days):
            return None, paid, i
        floor = hwm - ML * A
        if lock:
            floor = min(floor, A)
        d, trs = days[k]
        s = min(1.0, max(0.25, (bal - floor) / (ML * A))) if buffer else 1.0
        x = X * s
        cur = 0.0
        if not (skip_th and prev is not None and prev > skip_th * x):
            dloss_lim = -DL * bal                      # FTMO daily limit (from midnight balance)
            g_lim = max(-guard * bal, (floor + 0.005 * A) - bal)
            for (pu, mu, fu, et, side) in trs:
                if cur + x * mu <= g_lim:
                    cur = g_lim
                    if cur <= dloss_lim or bal + cur <= floor:
                        return i + 1, paid, i + 1
                    if bal + cur <= floor + 0.005 * A + 1:
                        return i + 1, paid, i + 1     # floor guard: account stuck = dead
                    break
                if cap is not None and cur + x * fu >= cap:
                    cur = cap; break                  # daily profit cap in $ (TP at the cap, then stop)
                cur += x * pu
                if cap is not None and cur >= cap:
                    break
            prev = cur
        else:
            prev = 0.0
        bal += cur; hwm = max(hwm, bal)
        period_days.append(cur)
        if i >= every and i % every == 0:
            prof = bal - per_start_bal
            best = max(period_days) if period_days else 0
            floor = min(hwm - ML * A, A) if lock else hwm - ML * A
            w = min(prof, bal - floor - keep)
            if prof > 0 and best <= cons * prof and w > 0:
                paid += split * w; bal -= w
                per_start_bal, period_days = bal, []
    return None, paid, horizon


starts = [s for s in range(0, len(F.days) - 3 * YEAR)][::3]
if __name__ == "__main__":
    print(len(starts), "starts", F.days[starts[0]][0], F.days[starts[-1]][0])
