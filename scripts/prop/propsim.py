"""Prop-firm rule simulators driven by per-day trade lists (NQ points per 1 NQ contract).

Sizing is in MNQ micros ($2/pt) for Apex and in fractional $/pt for FTMO US100 CFD.
Each sim starts an attempt on every trading day in history and reports outcome stats.
"""
import math, numpy as np

MICRO = 2.0          # $ per NQ point per MNQ
COST_MICRO = 2.5     # $ round turn per MNQ: commissions+fees (~$1.3) + 1 tick slippage ($0.5) x ~2


def size_micros(tr, risk_usd, fixed, cap):
    if fixed:
        return min(fixed, cap)
    if tr["risk_pts"] <= 0:
        return 0
    return max(0, min(cap, math.floor(risk_usd / (tr["risk_pts"] * MICRO))))


def play_day(trades, risk_usd, fixed, cap, dll, cost):
    """Return (day_pnl, day_min_pnl) in $. DLL liquidates and stops the day."""
    pnl, low = 0.0, 0.0
    for tr in trades:
        n = size_micros(tr, risk_usd, fixed, cap)
        if n == 0:
            continue
        worst = pnl + tr["mae_pts"] * MICRO * n - cost * n
        if dll and worst <= -dll:
            return -dll, -dll
        low = min(low, worst)
        pnl += tr["pnl_pts"] * MICRO * n - cost * n
        low = min(low, pnl)
    return pnl, low


def apex_eval(days, start, risk_usd=0, fixed=0, size=50, max_tdays=21):
    P = {25: (1500, 1000, 500, 40), 50: (3000, 2000, 1000, 60), 100: (6000, 3000, 1500, 80), 150: (9000, 4000, 2000, 120)}
    target, dd, dll, cap = P[size]
    bal = peak = 0.0
    for k in range(max_tdays):
        if start + k >= len(days):
            return "end", k
        pnl, low = play_day(days[start + k], risk_usd, fixed, cap, dll, COST_MICRO)
        thr = peak - dd
        if bal + low <= thr:
            return "fail", k + 1
        bal += pnl
        if bal >= target:
            return "pass", k + 1
        peak = max(peak, bal)
    return "timeout", max_tdays


def apex_pa(days, start, risk_usd=0, fixed=0, size=50, max_tdays=252):
    """50K PA: EOD trail $2000 until threshold locks at +100; payouts per 2026 rules."""
    assert size == 50
    dd, lock, net_min, min_bal, qual = 2000, 100, 2100, 2600, 250
    caps = [1500, 1800, 2100, 2400, 2700, 3000]
    tiers = [(0, 20, 1000), (1500, 30, 1000), (3000, 40, 2000), (6000, 40, 3000)]
    bal = peak = 0.0
    paid, q, since, best = [], 0, 0.0, 0.0
    for k in range(max_tdays):
        if start + k >= len(days):
            break
        prof = bal
        cap, dll = [(c, d) for t, c, d in tiers if max(prof, 0) >= t][-1]
        pnl, low = play_day(days[start + k], risk_usd, fixed, cap, dll, COST_MICRO)
        thr = min(peak - dd, lock)
        if bal + low <= thr:
            return dict(result="breach", payouts=paid, days=k + 1)
        bal += pnl
        peak = max(peak, bal)
        since += pnl
        best = max(best, pnl)
        if pnl >= qual:
            q += 1
        if q >= 5 and bal >= min_bal and since > 0 and best < 0.5 * since:
            amt = min(caps[len(paid)], bal - net_min)
            if amt >= 500:
                paid.append(amt)
                bal -= amt
                peak = max(peak - amt, bal)  # threshold already locked at +100 once bal>=2100
                q, since, best = 0, 0.0, 0.0
                if len(paid) == 6:
                    return dict(result="maxed", payouts=paid, days=k + 1)
    return dict(result="open", payouts=paid, days=k + 1)


def ftmo_phase(days, start, target_pct, risk_pct, acct=100_000, dl_pct=0.05, ml_pct=0.10,
               min_days=4, max_tdays=250, cost_pts=1.5):
    """FTMO 2-Step on US100.cash: static 10% max loss, 5% daily loss from day-start balance
    (equity-based). Size = risk_pct of initial capital per trade / stop distance."""
    bal, traded = 0.0, 0
    for k in range(max_tdays):
        if start + k >= len(days):
            return "end", k
        pnl, low = 0.0, 0.0
        for tr in days[start + k]:
            if tr["risk_pts"] <= 0:
                continue
            dpp = risk_pct * acct / tr["risk_pts"]   # $ per point
            low = min(low, pnl + (tr["mae_pts"] - cost_pts) * dpp)
            pnl += (tr["pnl_pts"] - cost_pts) * dpp
            low = min(low, pnl)
        if days[start + k]:
            traded += 1
        if low <= -dl_pct * acct or bal + low <= -ml_pct * acct:
            return "fail", k + 1
        bal += pnl
        if bal >= target_pct * acct and traded >= min_days:
            return "pass", k + 1
    return "timeout", max_tdays


def summarize(results):
    n = len(results)
    out = {}
    for r in set(x[0] for x in results):
        out[r] = round(100 * sum(1 for x in results if x[0] == r) / n, 1)
    out["avg_days_pass"] = round(np.mean([x[1] for x in results if x[0] == "pass"]), 1) if any(x[0] == "pass" for x in results) else None
    return out


def ftmo_day(trades, dpp, cost_pts):
    pnl, low = 0.0, 0.0
    for tr in trades:
        low = min(low, pnl + (tr["mae_pts"] - cost_pts) * dpp)
        pnl += (tr["pnl_pts"] - cost_pts) * dpp
        low = min(low, pnl)
    return pnl, low


def ftmo2(days, start, dpp, acct=100_000, cost_pts=1.5, max_tdays=250):
    """Full FTMO 2-Step: phase1 10% then phase2 5% (fresh balance), 5% daily, 10% static, 4 min days."""
    k = start
    for tgt in (0.10, 0.05):
        bal, traded = 0.0, 0
        while True:
            if k >= len(days) or k - start > max_tdays:
                return "timeout", k - start
            pnl, low = ftmo_day(days[k], dpp, cost_pts)
            k += 1
            traded += bool(days[k - 1])
            if low <= -0.05 * acct or bal + low <= -0.10 * acct:
                return "fail", k - start
            bal += pnl
            if bal >= tgt * acct and traded >= 4:
                break
    return "pass", k - start


def ftmo_funded(days, start, dpp, acct=100_000, cost_pts=1.5, split=0.8, horizon=252):
    """Funded 2-Step account: static 10% max loss, 5% daily; withdraw profit above start every 10 trading days."""
    bal, paid = 0.0, 0.0
    for i in range(horizon):
        k = start + i
        if k >= len(days):
            break
        pnl, low = ftmo_day(days[k], dpp, cost_pts)
        if low <= -0.05 * acct or bal + low <= -0.10 * acct:
            return paid, "breach"
        bal += pnl
        if i >= 10 and i % 10 == 0 and bal > 0:
            paid += split * bal
            bal = 0.0
    return paid, "alive"


def ftmo1(days, start, dpp, acct=100_000, cost_pts=1.5, max_tdays=250):
    """FTMO 1-Step: 10% target, 3% daily loss (equity vs day-start balance), 10% max loss trailing
    on end-of-day balance highs, 50% consistency (best day <= 50% of total net profit)."""
    bal, peak, best = 0.0, 0.0, 0.0
    for k in range(max_tdays):
        if start + k >= len(days):
            return "end", k
        pnl, low = ftmo_day(days[start + k], dpp, cost_pts)
        if low <= -0.03 * acct or bal + low <= peak - 0.10 * acct:
            return "fail", k + 1
        bal += pnl
        peak = max(peak, bal)
        best = max(best, pnl)
        if bal >= 0.10 * acct and best <= 0.5 * bal:
            return "pass", k + 1
    return "timeout", max_tdays


def ftmo_day_dyn(trades, dpp, cost_pts, day_stop=None):
    """Like ftmo_day, but stops taking new trades once the day is down `day_stop` dollars."""
    pnl, low = 0.0, 0.0
    for tr in trades:
        if day_stop is not None and pnl <= -day_stop:
            break
        low = min(low, pnl + (tr["mae_pts"] - cost_pts) * dpp)
        pnl += (tr["pnl_pts"] - cost_pts) * dpp
        low = min(low, pnl)
    return pnl, low


def scale_fn(bal, acct, power, floor_pct=0.10, minscale=0.25):
    """Size multiplier from distance to the max-loss floor: 1 at start, shrinks as the buffer shrinks."""
    buf = (bal + floor_pct * acct) / (floor_pct * acct)
    return max(minscale, min(1.0, buf)) ** power if power else 1.0


def ftmo2_dyn(days, start, dpp, acct=100_000, cost_pts=1.5, max_tdays=250, power=0, day_stop_pct=None):
    k = start
    for tgt in (0.10, 0.05):
        bal, traded = 0.0, 0
        while True:
            if k >= len(days) or k - start > max_tdays:
                return "timeout", k - start
            d = dpp * scale_fn(bal, acct, power)
            pnl, low = ftmo_day_dyn(days[k], d, cost_pts, day_stop_pct * acct if day_stop_pct else None)
            k += 1
            traded += bool(days[k - 1])
            if low <= -0.05 * acct or bal + low <= -0.10 * acct:
                return "fail", k - start
            bal += pnl
            if bal >= tgt * acct and traded >= 4:
                break
    return "pass", k - start


def ftmo_funded_dyn(days, start, dpp, acct=100_000, cost_pts=1.5, split=0.8, horizon=252, power=0, day_stop_pct=None):
    bal, paid = 0.0, 0.0
    for i in range(horizon):
        k = start + i
        if k >= len(days):
            break
        d = dpp * scale_fn(bal, acct, power)
        pnl, low = ftmo_day_dyn(days[k], d, cost_pts, day_stop_pct * acct if day_stop_pct else None)
        if low <= -0.05 * acct or bal + low <= -0.10 * acct:
            return paid, "breach"
        bal += pnl
        if i >= 10 and i % 10 == 0 and bal > 0:
            paid += split * bal
            bal = 0.0
    return paid, "alive"
