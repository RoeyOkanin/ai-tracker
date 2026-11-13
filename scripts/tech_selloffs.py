"""Where does the money go when tech falls?  Measured, not told.

1. Episodes: every fall of 15%+ in QQQ since 1999 (zig-zag: a fall counts once
   it is 15% below the peak; it ends when the price rallies 15% off the low).
2. Cause of each fall, from market data over the fall itself (thresholds fixed in advance;
   all from Yahoo, because FRED blocks GitHub Actions):
     recession / credit : junk bonds (Vanguard High-Yield fund) lag Treasuries
                          (Vanguard Intermediate Treasury fund) by 5% or more
     rates / inflation  : (else) the 5-year or 10-year Treasury yield rises 0.5 pt or more
     valuation / other  : neither
3. What every refuge did during each fall: sectors, small caps, value, equal weight,
   abroad, real estate, gold, long and medium Treasuries, dollar, commodities, cash.
4. Rule test (all fixed before the run), checked at each month-end, executed next close:
     TECH         always SMH (or QQQ)
     TECH_CASH    tech above its 200-day average, else T-bills
     TECH_BEST2   ... else the 2 refuges with the best 6-month return (a refuge that
                  did worse than T-bills is replaced by T-bills)
     TECH_CAUSE   ... else the best 2 inside the basket that fits today's cause
                  (cause measured over the last 6 months, data known at that date)
   plus 20 placebos of TECH_BEST2 with random refuges.

Usage (GitHub Actions): python scripts/tech_selloffs.py
"""
from __future__ import annotations

import io
import json
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

from engine import DATA, perf_stats, yearly_returns

OUT = DATA / "research"
RAW = DATA / "broad"
TH = 0.15
COST = 0.0015

TECH = ["QQQ", "SMH", "XLK"]
REFUGES = {
    "XLE": "אנרגיה", "XLU": "תשתיות חשמל ומים", "XLV": "בריאות", "XLP": "צריכה בסיסית",
    "XLF": "פיננסים", "XLI": "תעשייה", "XLB": "חומרי גלם", "XLY": "צריכה מחזורית",
    "IWM": "מניות קטנות", "IWD": "מניות ערך", "RSP": "S&P במשקל שווה", "SPY": "S&P 500",
    "EFA": "חו\"ל מפותח", "EEM": "שווקים מתעוררים", "VNQ": "נדל\"ן",
    "GOLD": "זהב", "LONG_TSY": "אג\"ח ממשלתי ארוך", "IEF": "אג\"ח ממשלתי בינוני",
    "UUP": "דולר", "DBC": "סחורות", "CASH": "פיקדון קצר (T-bills)",
}
# baskets chosen from economics before looking at any result
BASKETS = {
    "rates": ["XLE", "XLP", "XLU", "XLV", "DBC", "IWD", "CASH"],
    "credit": ["LONG_TSY", "IEF", "GOLD", "XLP", "UUP", "CASH"],
    "other": ["IWM", "IWD", "RSP", "EFA", "VNQ", "XLV", "XLF", "XLI", "CASH"],
}
MACRO = ["^IRX", "^FVX", "^TNX", "VWEHX", "VFITX"]   # 3m bill, 5y, 10y yields; junk-bond and Treasury funds
YF = TECH + [t for t in REFUGES if t not in ("GOLD", "LONG_TSY", "CASH")] + ["GLD", "GC=F", "TLT", "VUSTX"] + MACRO


# ---------------------------------------------------------------- data
def load() -> pd.DataFrame:
    RAW.mkdir(parents=True, exist_ok=True)
    pf = RAW / "selloff_prices.pkl"
    if pf.exists():
        return pd.read_pickle(pf)
    import yfinance as yf
    raw = yf.download(YF, start="1998-01-01", auto_adjust=True, progress=False, group_by="column", threads=True)
    px = raw["Close"]
    px.index = pd.to_datetime([x.date() for x in px.index])
    missing = [t for t in YF if t not in px.columns or px[t].notna().sum() < 1000]
    print("missing / short:", missing, flush=True)
    px.to_pickle(pf)
    return px


def splice(new: pd.Series, old: pd.Series) -> pd.Series:
    """Older proxy before the ETF existed, rescaled to meet it."""
    new, old = new.dropna(), old.dropna()
    if new.empty:
        return old
    first = new.index[0]
    o = old.loc[:first]
    if o.empty:
        return new
    o = o / o.iloc[-1] * new.iloc[0]
    return pd.concat([o.iloc[:-1], new])


def build(px: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cal = px["SPY"].dropna().index
    p = px.reindex(cal).ffill(limit=5)
    p["GOLD"] = splice(px["GLD"], px["GC=F"]).reindex(cal).ffill(limit=5)
    p["LONG_TSY"] = splice(px["TLT"], px["VUSTX"]).reindex(cal).ffill(limit=5)

    def yld(t):
        y = px[t].reindex(cal).ffill(limit=5)
        return y / 10 if y.median() > 20 else y      # some feeds quote yield x10

    tb = yld("^IRX").ffill() / 100
    p["CASH"] = (1 + tb.shift(1).fillna(0) / 252).cumprod()
    macro = pd.DataFrame({"Y5": yld("^FVX"), "Y10": yld("^TNX"),
                          "HY": px["VWEHX"].reindex(cal).ffill(limit=5),
                          "TSY": px["VFITX"].reindex(cal).ffill(limit=5)}, index=cal).ffill()
    return p, macro


# ---------------------------------------------------------------- 1-3. episodes
def zigzag(s: pd.Series, th: float) -> list[tuple]:
    s = s.dropna()
    legs, state = [], "up"
    hi, hi_d = s.iloc[0], s.index[0]
    lo, lo_d = hi, hi_d
    for d, v in s.items():
        if state == "up":
            if v > hi:
                hi, hi_d = v, d
            if v <= hi * (1 - th):
                state, lo, lo_d = "down", v, d
        else:
            if v < lo:
                lo, lo_d = v, d
            if v >= lo * (1 + th):
                legs.append((hi_d, lo_d, False))
                state, hi, hi_d = "up", v, d
    if state == "down":
        legs.append((hi_d, lo_d, True))
    return legs


def classify(d_rates: float, credit_rel: float) -> str:
    if pd.notna(credit_rel) and credit_rel <= -0.05:
        return "credit"
    if pd.notna(d_rates) and d_rates >= 0.5:
        return "rates"
    return "other"


def episodes(p: pd.DataFrame, macro: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for a, b, ongoing in zigzag(p["QQQ"], TH):
        dm = macro.loc[a:b]
        d5 = dm["Y5"].iloc[-1] - dm["Y5"].iloc[0]
        d10 = dm["Y10"].iloc[-1] - dm["Y10"].iloc[0]
        cr = (dm["HY"].iloc[-1] / dm["HY"].iloc[0]) / (dm["TSY"].iloc[-1] / dm["TSY"].iloc[0]) - 1
        row = {"peak": a.date(), "trough": b.date(), "ongoing": ongoing, "days": (b - a).days,
               "qqq": p.at[b, "QQQ"] / p.at[a, "QQQ"] - 1,
               "d_5y": d5, "d_10y": d10, "junk_vs_treasury": cr,
               "yield_10y_at_peak": dm["Y10"].iloc[0],
               "cause": classify(max(d5, d10), cr)}
        for t in ["SMH"] + list(REFUGES):
            x = p[t]
            row[t] = (x.at[b] / x.at[a] - 1) if pd.notna(x.get(a)) and pd.notna(x.get(b)) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def pattern(ep: pd.DataFrame) -> dict:
    out = {}
    for cause, g in list(ep.groupby("cause")) + [("all", ep)]:
        stats = {}
        for t in REFUGES:
            v = g[t].dropna()
            if len(v) == 0:
                continue
            rel = (g[t] - g["qqq"]).dropna()
            stats[t] = {"name": REFUGES[t], "n": int(len(v)), "median": round(float(v.median()), 4),
                        "mean": round(float(v.mean()), 4), "pct_up": round(float((v > 0).mean()), 2),
                        "beat_qqq_by_median": round(float(rel.median()), 4)}
        ranked = sorted(stats.items(), key=lambda kv: -kv[1]["median"])
        out[cause] = {"episodes": int(len(g)), "qqq_median": round(float(g["qqq"].median()), 4),
                      "ranking": [{"ticker": k, **v} for k, v in ranked]}
    return out


# ---------------------------------------------------------------- 4. rule test
def cause_now(macro: pd.DataFrame, d) -> str:
    """Same thresholds, measured over the last 6 months with data known at d."""
    m = macro.loc[:d]                       # market closes, known at d
    if len(m) < 130:
        return "other"
    now, then = m.iloc[-1], m.iloc[-127]
    d_rates = max(now["Y5"] - then["Y5"], now["Y10"] - then["Y10"])
    return classify(d_rates, (now["HY"] / then["HY"]) / (now["TSY"] / then["TSY"]) - 1)


def backtest(p, macro, tech, start, mode, rng=None):
    cal = p.index
    rets = p.pct_change()
    mom = p / p.shift(126) - 1
    ma = p[tech].rolling(200, min_periods=200).mean()
    nxt = pd.Series(cal, index=cal).shift(-1)
    month_end = [d for d in cal if pd.notna(nxt[d]) and nxt[d].month != d.month]
    w = {}
    weights = pd.DataFrame(0.0, index=cal, columns=p.columns)
    state, picks_log = "tech", []
    for d in month_end:
        if d < pd.Timestamp(start) - pd.Timedelta(days=40) or pd.isna(ma[d]):
            continue
        px_, m_ = p.at[d, tech], ma[d]
        if mode == "TECH":
            state = "tech"
        elif px_ < m_ * 0.98:
            state = "off"
        elif px_ > m_:
            state = "tech"
        if state == "tech":
            new = {tech: 1.0}
        elif mode == "TECH_CASH":
            new = {"CASH": 1.0}
        else:
            pool = list(REFUGES) if mode in ("TECH_BEST2", "PLACEBO") else BASKETS[cause_now(macro, d)]
            pool = [t for t in pool if pd.notna(mom.at[d, t])]
            if mode == "PLACEBO":
                chosen = list(rng.choice(pool, size=2, replace=False))
            else:
                chosen = sorted(pool, key=lambda t: -mom.at[d, t])[:2]
                cash_m = mom.at[d, "CASH"]
                chosen = [t if mom.at[d, t] > cash_m else "CASH" for t in chosen]
            new = {}
            for t in chosen:
                new[t] = new.get(t, 0) + 0.5
        picks_log.append({"date": d.date(), "state": state, "hold": new,
                          "cause": cause_now(macro, d) if state == "off" else None})
        w[d] = new
    # daily returns: weights decided at d apply from d+2 (executed at close of d+1)
    dec = sorted(w)
    r = pd.Series(0.0, index=cal)
    cur, prev = {}, {}
    pending = None
    for i, d in enumerate(cal):
        if cur:
            r[d] = sum(wt * (rets.at[d, t] if pd.notna(rets.at[d, t]) else 0.0) for t, wt in cur.items())
        if pending is not None:
            turnover = sum(abs(pending.get(t, 0) - cur.get(t, 0)) for t in set(pending) | set(cur))
            r[d] -= turnover * COST
            cur, pending = pending, None
        if d in w:
            pending = w[d]
    nav = (1 + r.loc[start:]).cumprod()
    return nav, picks_log


def main() -> None:
    px = load()
    p, macro = build(px)
    ep = episodes(p, macro)
    pat = pattern(ep)
    print(ep[["peak", "trough", "qqq", "d_5y", "d_10y", "junk_vs_treasury", "cause"]].round(3).to_string())
    for c, v in pat.items():
        print(c, v["episodes"], [(x["ticker"], x["median"], x["pct_up"]) for x in v["ranking"][:6]])

    results, yearly, navs, now = {}, {}, {}, {}
    for tech, start in (("QQQ", "2000-06-01"), ("SMH", "2001-06-01")):
        periods = {"first_half": (start, "2012-12-31"), "second_half": ("2013-01-01", None), "full": (start, None)}
        for mode in ("TECH", "TECH_CASH", "TECH_BEST2", "TECH_CAUSE"):
            nav, log = backtest(p, macro, tech, start, mode)
            key = f"{tech}:{mode}"
            navs[key] = nav
            yearly[key] = yearly_returns(nav)
            results[key] = {pk: {k: round(float(v), 4) for k, v in perf_stats(nav.loc[a:b] / nav.loc[a:b].iloc[0]).items()}
                            for pk, (a, b) in periods.items()}
            if mode in ("TECH_BEST2", "TECH_CAUSE"):
                now[key] = log[-1] if log else None
            print(key, {pk: (v["cagr"], v["max_drawdown"]) for pk, v in results[key].items()}, flush=True)
        plc = []
        for seed in range(20):
            nav, _ = backtest(p, macro, tech, start, "PLACEBO", rng=np.random.default_rng(seed))
            plc.append(round(perf_stats(nav)["cagr"], 4))
        results[f"{tech}:PLACEBO_random_refuges"] = {"full_cagr_all": plc, "max": max(plc), "median": float(np.median(plc))}
        print(tech, "placebo", plc, flush=True)

    ep.to_csv(OUT / "tech_selloffs_episodes.csv", index=False, float_format="%.4f")
    pd.DataFrame(yearly).to_csv(OUT / "tech_selloffs_yearly.csv", float_format="%.4f", index_label="year")
    pd.DataFrame(navs).to_csv(OUT / "tech_selloffs_nav.csv", float_format="%.5f", index_label="date")
    d = p.index[-1]
    (OUT / "tech_selloffs_summary.json").write_text(json.dumps({
        "asof": str(d.date()), "threshold": TH, "pattern_by_cause": pat, "rules": results,
        "cause_today": cause_now(macro, d), "macro_today": macro.iloc[-1].round(3).to_dict(),
        "smh_vs_ma200": round(float(p["SMH"].iloc[-1] / p["SMH"].rolling(200).mean().iloc[-1] - 1), 4),
        "last_decisions": now, "baskets": BASKETS,
    }, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print((pd.DataFrame(yearly) * 100).round(1).to_string())


if __name__ == "__main__":
    main()
