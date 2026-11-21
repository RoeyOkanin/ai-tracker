"""Fast re-implementation of strategies.noise_momentum that also records entry/exit times, side and
MFE (for intraday target-stop simulation). Output per day: list of trades with RAW NQ points
(QQQ x 41); sizing and costs are applied later in the simulator.
Checked against strategies.noise_momentum (same trades) in verify()."""
import sys, pickle, numpy as np, pandas as pd
sys.path.insert(0, "..")
import strategies as S

SP = "/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/"
K = S.NQ_PER_QQQ


def prep(df):
    days = sorted(df.date.unique())
    g = {d: x for d, x in df.groupby("date")}
    return days, g


def noise_trades(days, g, lookback=14, vm=1.0, block=(), last_entry_min=930, first_entry_min=600, exit_min=955):
    """Times are minutes of the NY day at BAR END (bar start + 5). Decisions on :00/:30 bar ends."""
    # move-from-open table per day, keyed by bar-start HH:MM
    mv = {}
    for d in days:
        x = g[d]
        hm = x.index.hour * 60 + x.index.minute
        mv[d] = pd.Series(np.abs(x.close.values / x.open.values[0] - 1), index=hm).groupby(level=0).last()
    blockm = set(int(t[:2]) * 60 + int(t[3:]) for t in block)
    out = {}
    prev_close = None
    for i, d in enumerate(days):
        x = g[d]
        if i < lookback or len(x) < 60 or prev_close is None:
            prev_close = x.close.iloc[-1]
            continue
        sig = pd.concat([mv[days[j]] for j in range(i - lookback, i)], axis=1).mean(axis=1) * vm
        o = x.open.values[0]
        up_base, dn_base = max(o, prev_close), min(o, prev_close)
        cl, hi, lo, vol = x.close.values, x.high.values, x.low.values, x.volume.values
        cv = np.cumsum(cl * vol); vv = np.cumsum(vol)
        with np.errstate(invalid="ignore", divide="ignore"):
            pv = np.where(vv > 0, cv / vv, np.nan)
        start_m = x.index.hour * 60 + x.index.minute
        pos, entry, mae, mfe, et = 0, 0.0, 0.0, 0.0, 0
        trades = []
        for k in range(len(x)):
            sm = start_m[k]
            s = sig.get(sm, np.nan)
            if np.isnan(s):
                continue
            ub, lb = up_base * (1 + s), dn_base * (1 - s)
            if pos:
                if pos == 1:
                    mae = min(mae, lo[k] - entry); mfe = max(mfe, hi[k] - entry)
                else:
                    mae = min(mae, entry - hi[k]); mfe = max(mfe, entry - lo[k])
            em = sm + 5
            on_half = (em % 30 == 0)
            if pos and (on_half or sm >= exit_min):
                stop = max(ub, pv[k]) if pos == 1 else min(lb, pv[k])
                hit = (pos == 1 and cl[k] < stop) or (pos == -1 and cl[k] > stop)
                if hit or sm >= exit_min:
                    trades.append(dict(et=et, xt=em, side=pos, pts=pos * (cl[k] - entry) * K, mae=mae * K, mfe=mfe * K,
                                       eod=bool(sm >= exit_min)))
                    pos = 0
                    if sm >= exit_min:
                        break
            if not pos and on_half and em >= first_entry_min and em <= last_entry_min and em not in blockm:
                if cl[k] > ub:
                    pos, entry, mae, mfe, et = 1, cl[k], 0.0, 0.0, em
                elif cl[k] < lb:
                    pos, entry, mae, mfe, et = -1, cl[k], 0.0, 0.0, em
        if pos:
            trades.append(dict(et=et, xt=int(start_m[-1] + 5), side=pos, pts=pos * (cl[-1] - entry) * K, mae=mae * K, mfe=mfe * K, eod=True))
        out[d] = trades
        prev_close = x.close.iloc[-1]
    return out


def daily(df):
    gd = df.groupby("date")
    D = pd.DataFrame(dict(o=gd.open.first(), c=gd.close.last(), h=gd.high.max(), l=gd.low.min()))
    D["ret"] = D.c.pct_change()
    D["vol14"] = D.ret.rolling(14).std().shift(1)
    D["lvl"] = D.o * K
    return D


if __name__ == "__main__":
    q = S.load("../../../data/prop/QQQ_5m.csv.gz")
    days, g = prep(q)
    D = daily(q)
    res = {"daily": D}
    for name, blk in [("base", ()), ("b12_14", ("12:00", "14:00"))]:
        res[name] = noise_trades(days, g, block=blk)
        print(name, sum(len(v) for v in res[name].values()), flush=True)
    # verify against the original implementation on a slice
    sl = q[q.date >= pd.Timestamp("2024-01-01").date()]
    orig = S.noise_momentum(sl)
    d2, g2 = prep(sl)
    mine = noise_trades(d2, g2)
    a = sum(t["pnl_pts"] for v in orig.values() for t in v); b = sum(t["pts"] for v in mine.values() for t in v)
    na = sum(len(v) for v in orig.values()); nb = sum(len(v) for v in mine.values())
    print("verify 2024+: orig", round(a, 1), na, "| mine", round(b, 1), nb)
    pickle.dump(res, open(SP + "g70_trades.pkl", "wb"))
