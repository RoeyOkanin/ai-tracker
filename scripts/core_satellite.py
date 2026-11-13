"""Core + satellite: most of the money in a simple core, a slice in the rotation.

Cores:  SMH (buy & hold)  |  the whole physical AI chain, equal weight
        (every physical-chain stock that is liquid at that month-end: price >= $5,
        60-day dollar volume >= $20M; rebalanced monthly, 0.15% per side).
Satellite: version H (physical chain, 6 holdings, $100M/day), NAV from
        data/research/bottleneck_nav.csv (same engine, same data).
Mixes are rebalanced once a year (fewer taxable sales).

Usage (GitHub Actions): python scripts/core_satellite.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from broad_research import BENCH, MIN_DOLLAR_VOL, MIN_PRICE, download
from bottleneck_research import IS_END, IS_START, OOS_START, OUT, PHYS, RAW
from engine import perf_stats, yearly_returns

COST = 0.0015


def equal_weight_chain(px: pd.DataFrame, liquid: pd.DataFrame, start: str) -> pd.Series:
    cal = px.index
    s = pd.Series(cal, index=cal)
    month_ends = pd.DatetimeIndex(s.groupby(cal.to_period("M")).max().values)
    month_ends = month_ends[month_ends >= pd.Timestamp(start) - pd.Timedelta(days=40)]
    nav, value, prev_w = [], 1.0, pd.Series(dtype=float)
    for i, d in enumerate(month_ends):
        j = cal.get_loc(d) + 1                      # buy at the next close
        if j >= len(cal):
            break
        k = cal.get_loc(month_ends[i + 1]) + 1 if i + 1 < len(month_ends) else len(cal) - 1
        k = min(k, len(cal) - 1)
        names = liquid.columns[liquid.loc[d].values]
        names = [t for t in names if pd.notna(px.iat[j, px.columns.get_loc(t)])]
        if not names:
            continue
        w = pd.Series(1 / len(names), index=names)
        turnover = w.subtract(prev_w, fill_value=0).abs().sum()
        value *= 1 - COST * turnover
        seg = px.iloc[j:k + 1][names].ffill()
        rel = seg / seg.iloc[0]
        path = value * (rel * w).sum(axis=1)
        nav.append(path.iloc[1:] if nav else path)
        end = rel.iloc[-1] * w
        value = float(path.iloc[-1])
        prev_w = end / end.sum()
    out = pd.concat(nav)
    out = out[~out.index.duplicated()]
    out = out.loc[start:]
    return out / out.iloc[0]


def mix(a: pd.Series, b: pd.Series, wa: float) -> pd.Series:
    """wa in a, rest in b, back to target once a year."""
    idx = a.index.intersection(b.index)
    ra, rb = a.reindex(idx).pct_change().fillna(0), b.reindex(idx).pct_change().fillna(0)
    va, vb, prev, out = wa, 1 - wa, None, []
    for d in idx:
        if prev is not None and d.year != prev:
            t = va + vb
            va, vb = t * wa, t * (1 - wa)
        va *= 1 + ra[d]
        vb *= 1 + rb[d]
        prev = d.year
        out.append(va + vb)
    return pd.Series(out, index=idx)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    u = pd.read_csv(OUT / "broad_universe.csv")
    u = u[u["bucket"].isin(PHYS)]
    if (RAW / "close.pkl").exists():
        close, vol = pd.read_pickle(RAW / "close.pkl"), pd.read_pickle(RAW / "vol.pkl")
    else:
        close, vol = download(u["ticker"].tolist() + BENCH)
        close.to_pickle(RAW / "close.pkl")
        vol.to_pickle(RAW / "vol.pkl")
    tick = [t for t in u["ticker"] if t in close.columns and close[t].notna().sum() > 260]
    cal = close["SPY"].dropna().index
    px = close.reindex(cal).ffill(limit=5)
    px = px.where(px > 0)
    dv = (close * vol).reindex(cal).rolling(60, min_periods=40).mean()
    liquid = ((px[tick] >= MIN_PRICE) & (dv[tick] >= MIN_DOLLAR_VOL)).fillna(False)

    navs = pd.read_csv(OUT / "bottleneck_nav.csv", index_col=0, parse_dates=True)
    H = navs.iloc[:, 0].dropna()
    smh = px["SMH"].loc[IS_START:].dropna()
    smh = smh / smh.iloc[0]
    ew = equal_weight_chain(px[tick], liquid, IS_START)

    combos = {
        "SMH 100%": smh,
        "שרשרת במשקל שווה 100%": ew,
        "רוטציה H 100%": H,
        "SMH 70% + H 30%": mix(smh, H, 0.7),
        "SMH 50% + H 50%": mix(smh, H, 0.5),
        "שרשרת שווה 70% + H 30%": mix(ew, H, 0.7),
        "שרשרת שווה 50% + H 50%": mix(ew, H, 0.5),
        "SMH 50% + שרשרת שווה 50%": mix(smh, ew, 0.5),
    }
    periods = {"calibration_2018_2022": (IS_START, IS_END), "out_of_sample_2023_2026": (OOS_START, None),
               "full_2018_2026": (IS_START, None)}
    res, yearly = {}, {}
    for k, nav in combos.items():
        for pk, (a, b) in periods.items():
            seg = nav.loc[a:b].dropna()
            st = perf_stats(seg / seg.iloc[0])
            res.setdefault(k, {})[pk] = {m: round(float(v), 4) for m, v in st.items()}
        yearly[k] = yearly_returns(nav)
    (OUT / "core_satellite_summary.json").write_text(json.dumps({"results": res}, indent=1, ensure_ascii=False),
                                                     encoding="utf-8")
    pd.DataFrame(yearly).to_csv(OUT / "core_satellite_yearly.csv", float_format="%.4f", index_label="year")
    pd.DataFrame(combos).to_csv(OUT / "core_satellite_nav.csv", float_format="%.5f", index_label="date")
    pd.set_option("display.width", 220)
    print(pd.DataFrame({k: {f"{pk[:3]}_{m}": v[pk][m] for pk in v for m in ("cagr", "max_drawdown", "sharpe")}
                        for k, v in res.items()}).T)
    print((pd.DataFrame(yearly) * 100).round(1))


if __name__ == "__main__":
    main()
