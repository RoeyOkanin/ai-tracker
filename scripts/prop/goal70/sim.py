"""FTMO 2-Step challenge simulator that mirrors the MT5 EA:
 - size per day = X ($ per normalized NQ point) x vol-scale, fixed at the day start
 - cost 5 normalized pts per trade (x vol-scale), calibrated from MT5 tester vs python (2025-11..2026-11)
 - EA guards: daily -4.5% of initial (close + stop for the day), floor guard at 90.5k (close; account is stuck = fail)
 - skip-after-win: skip today if yesterday's realized $ > TH x X (EA-consistent: only real P&L counts)
 - optional target-stop: close at the target intraday (adverse excursion assumed to come first) and finish
   the minimum trading days with micro trades
Phase 1: +10%, phase 2: +5% (fresh 100k), min 4 trading days each, 10% static max loss, 5% daily loss."""
import pickle, numpy as np, pandas as pd

SP = "/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/"
A = 100_000.0
R = pickle.load(open(SP + "g70_trades.pkl", "rb"))
D = R["daily"]


def build(variant="b12_14", cap=2.0, vt=0.012, cost=5.0, max_entries=None, day_filter=None):
    """Return list of (date, [(pnl_u, mae_u, mfe_u, et, side)]) in $ per $1/pt of base size."""
    tr = R[variant]
    out = []
    for d in sorted(tr):
        v = D.vol14.get(d)
        if v is None or not np.isfinite(v):
            continue
        vs = min(cap, vt / v)
        n = 25000.0 / D.lvl[d]
        ts = tr[d]
        if day_filter is not None and not day_filter.get(d, True):
            ts = []
        if max_entries is not None:
            # EA merges exit+re-entry on the same side and bar into one position: count entries that way
            kept, entries, prev = [], 0, None
            for t in ts:
                cont = prev is not None and prev["xt"] == t["et"] and prev["side"] == t["side"]
                if not cont:
                    entries += 1
                if entries > max_entries:
                    break
                kept.append(t); prev = t
            ts = kept
        out.append((d, [(vs * n * t["pts"] - cost * vs, vs * n * t["mae"] - cost * vs, vs * n * t["mfe"] - cost * vs,
                         t["et"], t["side"]) for t in ts]))
    return out


def fixed(x1, x2=None):
    x2 = x1 if x2 is None else x2
    return lambda phase, bal: x1 if phase == 1 else x2


def cushion(x1, x2=None, p=1.0, lo=0.25, hi=1.0):
    """size x clip(distance to floor / 10%, lo, hi)^p ; 1.0 at the phase start."""
    x2 = x1 if x2 is None else x2
    def f(phase, bal):
        s = min(hi, max(lo, (bal + 0.10 * A) / (0.10 * A))) ** p
        return (x1 if phase == 1 else x2) * s
    return f


def attempt(days, start, sizing, skip_th=167.0, target_stop=False, max_days=504, gap=0):
    k = start
    for phase, tgt in ((1, 0.10 * A), (2, 0.05 * A)):
        bal, traded, prev_real, locked = 0.0, 0, None, False
        while True:
            if k >= len(days) or k - start >= max_days:
                return "timeout", k - start
            d, trs = days[k]; k += 1
            if locked:
                traded += 1               # micro trade to complete the minimum trading days
                if traded >= 4:
                    break
                continue
            X = sizing(phase, bal)
            if skip_th and prev_real is not None and prev_real > skip_th * X:
                prev_real = 0.0
                continue
            cur, any_trade, floor_hit = 0.0, False, False
            lim_floor = (-0.10 * A + 0.005 * A) - bal
            lim = max(-0.045 * A, lim_floor)
            for (pu, mu, fu, et, side) in trs:
                any_trade = True
                if cur + X * mu <= lim:
                    cur = lim; floor_hit = lim == lim_floor
                    break
                if target_stop and bal + cur + X * fu >= tgt:
                    cur = tgt - bal; locked = True
                    break
                cur += X * pu
            if floor_hit:
                return "fail", k - start
            bal += cur
            traded += any_trade
            prev_real = cur
            if bal >= tgt:
                if traded >= 4:
                    break
                if target_stop:
                    locked = True
        k += gap
    return "pass", k - start


def evaluate(days, sizing, step=2, horizon12=252, **kw):
    """Pass within 12 months and within 24 months, by start era. Starts need enough runway."""
    dates = [d for d, _ in days]
    n = len(days)
    rows = []
    for s in range(0, n - 252, step):
        r, t = attempt(days, s, sizing, **kw)
        rows.append((dates[s], r, t))
    df = pd.DataFrame(rows, columns=["d", "r", "t"])
    df["era"] = np.where(pd.to_datetime(df.d) < "2022-01-01", "A", "B")
    df["p12"] = (df.r == "pass") & (df.t <= horizon12)
    runway = {dates[s]: n - s for s in range(n)}
    df["full24"] = df.d.map(runway) >= 504
    out = {}
    for era in ("A", "B", "all"):
        x = df if era == "all" else df[df.era == era]
        x24 = x[x.full24]
        out[era] = dict(p12=round(100 * x.p12.mean(), 1), p24=round(100 * (x24.r == "pass").mean(), 1),
                        fail24=round(100 * (x24.r == "fail").mean(), 1),
                        med=float(x[x.r == "pass"].t.median()) if (x.r == "pass").any() else None)
    return out, df


def fmt(out):
    return " | ".join(f"{e}: 12m {o['p12']:5.1f}% 24m {o['p24']:5.1f}% fail {o['fail24']:5.1f}% med {o['med']}" for e, o in out.items())


def build_mult(base_days, mult):
    """Scale each day's trades by a day multiplier known before the open."""
    out = []
    for d, trs in base_days:
        m = mult.get(d, 1.0)
        out.append((d, [(m * a, m * b, m * c, e, s) for (a, b, c, e, s) in trs]))
    return out


def regime_series():
    Dd = D.copy()
    for n in (50, 200):
        Dd[f"below{n}"] = Dd.c.shift(1) < Dd.c.rolling(n).mean().shift(1)
    return Dd


def funded(days, start, X, horizon=252, skip_th=167.0, buffer=True, split=0.8):
    """Funded account mirroring the EA: buffer scaling (size x clip(dist to floor / 10%, .25, 1)),
    guards, skip-after-win; profit above 100k withdrawn every 10 trading days (80% to trader)."""
    bal, paid, prev_real = 0.0, 0.0, None
    for i in range(horizon):
        k = start + i
        if k >= len(days):
            break
        d, trs = days[k]
        s = min(1.0, max(0.25, (bal + 0.10 * A) / (0.10 * A))) if buffer else 1.0
        x = X * s
        if skip_th and prev_real is not None and prev_real > skip_th * x:
            prev_real = 0.0
            continue
        cur = 0.0
        lim_floor = (-0.10 * A + 0.005 * A) - bal
        lim = max(-0.045 * A, lim_floor)
        hit = False
        for (pu, mu, fu, et, side) in trs:
            if cur + x * mu <= lim:
                cur = lim; hit = lim == lim_floor
                break
            cur += x * pu
        if hit:
            return paid, "breach"
        bal += cur; prev_real = cur
        if i >= 10 and i % 10 == 0 and bal > 0:
            paid += split * bal; bal = 0.0
    return paid, "alive"
