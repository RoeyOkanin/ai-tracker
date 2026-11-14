"""Intraday strategies on 5-minute RTH bars, expressed per 1 NQ-equivalent contract.

Each strategy returns, per trading day, a list of trades:
    dict(pnl_pts, mae_pts, risk_pts)
in NQ index points (QQQ return x NQ level), so the prop simulator can size in MNQ.
"""
import numpy as np, pandas as pd

NQ_PER_QQQ = 41.0  # NDX/QQQ ratio, ~stable; used to convert QQQ moves into NQ points


def load(path):
    df = pd.read_csv(path, parse_dates=["ts"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("America/New_York")
    df = df.set_index("ts").sort_index()
    t = df.index.time
    df = df[(t >= pd.Timestamp("09:30").time()) & (t < pd.Timestamp("16:00").time())]
    df["date"] = df.index.date
    return df


def orb(df, bar_minutes=5, target_r=10.0, min_body=0.0, exit_time="15:55"):
    """Zarattini & Aziz ORB: direction of the first N-minute range, stop at its far end,
    target = target_r x risk, else exit at exit_time."""
    out = {}
    nbars = bar_minutes // 5
    ex = pd.Timestamp(exit_time).time()
    for d, g in df.groupby("date"):
        if len(g) < 60:
            continue
        first = g.iloc[:nbars]
        o, c, hi, lo = first.open.iloc[0], first.close.iloc[-1], first.high.max(), first.low.min()
        if abs(c - o) <= min_body * o:
            out[d] = []
            continue
        side = 1 if c > o else -1
        rest = g.iloc[nbars:]
        entry = rest.open.iloc[0]
        stop = lo if side == 1 else hi
        risk = abs(entry - stop)
        if risk <= 0:
            out[d] = []
            continue
        tgt = entry + side * target_r * risk
        mae = 0.0
        exitp = None
        for ts, b in rest.iterrows():
            adverse = (b.low - entry) if side == 1 else (entry - b.high)
            if side == 1 and b.low <= stop:
                exitp = stop; mae = min(mae, stop - entry); break
            if side == -1 and b.high >= stop:
                exitp = stop; mae = min(mae, entry - stop); break
            mae = min(mae, adverse)
            if side == 1 and b.high >= tgt:
                exitp = tgt; break
            if side == -1 and b.low <= tgt:
                exitp = tgt; break
            if ts.time() >= ex:
                exitp = b.close; break
        if exitp is None:
            exitp = rest.close.iloc[-1]
        k = NQ_PER_QQQ
        out[d] = [dict(pnl_pts=side * (exitp - entry) * k, mae_pts=mae * k, risk_pts=risk * k)]
    return out


def noise_momentum(df, lookback=14, vm=1.0, use_vwap=True, last_entry="15:30", exit_time="15:55", shift=()):
    """Concretum 'Beat the Market' intraday momentum, checks every 30 minutes.
    Noise band from avg |move from open| at the same time of day over `lookback` days.
    `shift`: checkpoint times (bar-end "HH:MM") moved 5 minutes later, e.g. ("10:00","14:00")
    to stay out of FTMO's 2-minute news blackout around 10:00 / 14:00 ET releases."""
    checks = set(f"{h:02d}:{m:02d}" for h in range(10, 17) for m in (0, 30))
    for t in shift:
        checks.discard(t)
        checks.add((pd.Timestamp(t) + pd.Timedelta(minutes=5)).strftime("%H:%M"))
    days = sorted(df.date.unique())
    g = {d: x for d, x in df.groupby("date")}
    # move from open at each time-of-day
    mv = {}
    for d in days:
        x = g[d]
        mv[d] = (x.close / x.open.iloc[0] - 1).abs().groupby(x.index.strftime("%H:%M")).last()
    out = {}
    prev_close = None
    le, ex = pd.Timestamp(last_entry).time(), pd.Timestamp(exit_time).time()
    for i, d in enumerate(days):
        x = g[d]
        if i < lookback or len(x) < 60 or prev_close is None:
            prev_close = x.close.iloc[-1]
            continue
        sigma = pd.concat([mv[days[j]] for j in range(i - lookback, i)], axis=1).mean(axis=1) * vm
        o = x.open.iloc[0]
        up_base, dn_base = max(o, prev_close), min(o, prev_close)
        pv = (x.close * x.volume).cumsum() / x.volume.cumsum().replace(0, np.nan)
        pos, entry, mae, trades = 0, 0.0, 0.0, []
        for ts, b in x.iterrows():
            hm = ts.strftime("%H:%M")
            s = sigma.get(hm, np.nan)
            if np.isnan(s):
                continue
            ub, lb = up_base * (1 + s), dn_base * (1 - s)
            vw = pv.loc[ts]
            # track adverse excursion of an open position
            if pos:
                mae = min(mae, (b.low - entry) if pos == 1 else (entry - b.high))
            bar_end = (ts + pd.Timedelta(minutes=5))
            on_half = bar_end.strftime("%H:%M") in checks
            if pos and (on_half or ts.time() >= ex):
                stop = max(ub, vw) if (pos == 1 and use_vwap) else (min(lb, vw) if use_vwap else (lb if pos == 1 else ub))
                hit = (pos == 1 and b.close < stop) or (pos == -1 and b.close > stop)
                if hit or ts.time() >= ex:
                    trades.append(dict(pnl_pts=pos * (b.close - entry) * NQ_PER_QQQ, mae_pts=mae * NQ_PER_QQQ,
                                       risk_pts=abs(b.close - stop) * NQ_PER_QQQ))
                    pos = 0
                    if ts.time() >= ex:
                        break
            if not pos and on_half and bar_end.time() >= pd.Timestamp("10:00").time() and ts.time() < le:
                if b.close > ub:
                    pos, entry, mae = 1, b.close, 0.0
                elif b.close < lb:
                    pos, entry, mae = -1, b.close, 0.0
        if pos:
            trades.append(dict(pnl_pts=pos * (x.close.iloc[-1] - entry) * NQ_PER_QQQ, mae_pts=mae * NQ_PER_QQQ, risk_pts=0))
        out[d] = trades
        prev_close = x.close.iloc[-1]
    return out
