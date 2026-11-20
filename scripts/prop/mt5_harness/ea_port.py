"""Line-by-line Python port of IntradayMomentum.mq5 v2.00 decision logic (NOT the research code),
so EA behaviour can be checked independently against the research backtest and the live fills.

Bars: 5-min RTH bars (bar start 09:30..15:55 NY). One "session" = one NY date that has a 09:30 bar
(exactly the EA's `valid` sessions). Optional extra sessions (e.g. futures holiday sessions) can be
injected to see what the EA does with them.
"""
import math
from pathlib import Path
import numpy as np
import pandas as pd

QQQ = Path(__file__).resolve().parents[3] / "data/prop/QQQ_5m.csv.gz"


def load_sessions(path=QQQ):
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("America/New_York")
    df = df.set_index("ts").sort_index()
    m = df.index.hour * 60 + df.index.minute
    df = df[(m >= 570) & (m < 960)].copy()
    df["slot"] = (df.index.hour * 60 + df.index.minute - 570) // 5
    df["date"] = df.index.date
    out = []
    for d, g in df.groupby("date"):
        if (g.slot == 0).any():               # EA keeps sessions that have a 09:30 bar
            out.append((d, g))
    return out


def normalize_lots(x, step=0.01, vmin=0.01):
    lots = math.floor(x / step) * step       # MathFloor(lots / step) * step
    if lots < vmin:
        return 0.0
    return round(lots, 2)


def prepare(prior, lookback=14, trend_ma=50, vol_target=0.012, vol_cap=1.0, below_mult=1.5, dpp=10.0):
    """prior: list of (date, bars) sessions strictly before today. Returns dict or None (EA returns false)."""
    nv = len(prior)
    if nv < lookback + 1:
        return None
    sig = np.full(78, -1.0)
    sums = np.zeros(78); cnts = np.zeros(78)
    for d, g in prior[nv - lookback:]:
        o = g.open.values[g.slot.values == 0][0]
        for s, c in zip(g.slot.values, g.close.values):
            sums[s] += abs(c / o - 1.0); cnts[s] += 1
    ok = cnts > 0
    sig[ok] = sums[ok] / cnts[ok]
    closes = np.array([g.close.values[-1] for _, g in prior])
    prev_close = closes[-1]
    j0 = max(1, nv - 14)
    rets = closes[j0:nv] / closes[j0 - 1:nv - 1] - 1.0
    vol = rets.std(ddof=1) if len(rets) > 1 else 0.0
    if vol <= 0:
        return None
    vol_scale = min(vol_cap, vol_target / vol)
    tilt = 1.0
    if trend_ma > 0 and below_mult != 1.0 and nv >= trend_ma:
        ma = closes[nv - trend_ma:].mean()
        if closes[-1] < ma:
            tilt = below_mult
    return dict(sig=sig, prev_close=prev_close, vol=vol, vol_scale=vol_scale, tilt=tilt,
                dpp=dpp * vol_scale * tilt, nv=nv)


def run_day(g, P, blocked=False, no_entry=(720, 840), first_entry=600, last_entry=930,
            notional=25000.0, open_override=None, lot_from_price=True):
    """One NY day of the EA. Returns list of trades (entry/exit in the bar price units) and lots."""
    sl = g.slot.values; op = g.open.values; cl = g.close.values; vo = g.volume.values.astype(float)
    vo = np.where(vo <= 0, 1.0, vo)
    day_open = op[sl == 0][0]
    trades = []
    side, entry, et = 0, 0.0, None
    lots = None
    pv = np.cumsum(cl * vo); vv = np.cumsum(vo)
    for k in range(len(g)):
        s_start = 570 + 5 * sl[k]
        end = s_start + 5
        if end % 30 != 0 or end < 600 or end > 960:
            continue
        if end >= 959:            # EOD flatten at 15:59 runs before the 16:00 checkpoint
            break
        s = P["sig"][sl[k]]
        if s < 0:
            continue
        if lots is None:
            ref = open_override if open_override else day_open
            lots = normalize_lots(P["dpp"] * notional / ref) if lot_from_price else P["dpp"] * notional / ref
        vwap = pv[k] / vv[k]
        close = cl[k]
        up = max(day_open, P["prev_close"]) * (1 + s)
        lo = min(day_open, P["prev_close"]) * (1 - s)
        exit_now = (side > 0 and close < max(up, vwap)) or (side < 0 and close > min(lo, vwap))
        want = 0
        win = first_entry <= end <= last_entry and end not in no_entry
        if win and not blocked:
            if close > up:
                want = 1
            elif close < lo:
                want = -1
        if side != 0 and exit_now:
            if want == side:
                continue                                  # HOLD
            trades.append(dict(side=side, entry=entry, exit=close, et=et, xt=end))
            side = 0
        if side == 0 and want != 0 and lots and lots > 0:
            side, entry, et = want, close, end
    if side != 0:
        trades.append(dict(side=side, entry=entry, exit=cl[-1], et=et, xt=959))   # EOD at last bar close
    return trades, lots, day_open


def replay(sessions, start=None, end=None, skip_pts=167.0, dpp=10.0, notional=25000.0, **kw):
    """Walk sessions like the EA. Day P&L in $ = dpp_day * notional * sum(side*(exit-entry))/open (no lot rounding)."""
    rows = []
    pnl_by_date = {}
    for i in range(len(sessions)):
        d, g = sessions[i]
        if start and d < start:
            continue
        if end and d > end:
            break
        P = prepare(sessions[:i], dpp=dpp, **kw)
        if P is None:
            continue
        prev_d = sessions[i - 1][0]
        blocked = skip_pts > 0 and pnl_by_date.get(prev_d, 0.0) > skip_pts * dpp
        trs, lots, o = run_day(g, P, blocked=blocked, notional=notional, lot_from_price=False)
        usd = sum(P["dpp"] * notional * t["side"] * (t["exit"] - t["entry"]) / o for t in trs)
        pnl_by_date[d] = usd
        rows.append(dict(date=d, n=len(trs), usd=usd, blocked=blocked, vol_scale=P["vol_scale"], tilt=P["tilt"],
                         dpp=P["dpp"], bars=len(g), trades=trs))
    return pd.DataFrame(rows)
