"""The switch from 2001: dot-com bust, 2008, the 2011 and 2015-16 chop, then the AI years.

Same code as the live system (build_switch), same rules, nothing re-tuned. Prices from 1999.
Benchmarks: SMH (listed May 2000) and QQQ (1999), both buy & hold.

Honest limits (printed in the summary too):
  - The stock list is today's physical-chain listings. Companies that died in 2000-2020
    (Nortel, JDSU's old form, Lucent, Sun, many fabless chips) are not in it. Before 2021
    there is no point-in-time list, so the stock side is survivor-biased, most of all in
    2000-2008. SMH_TREND (SMH with the cash rule) has no such bias: it only uses SMH.
  - The $100M-a-day liquidity bar is nominal. In 2001 far fewer stocks cleared it, so the
    rotation held fewer names and parked more in SMH.
Usage (GitHub Actions): python scripts/long_history.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import broad_research
from bottleneck_research import OUT, PHYS
from broad_research import MIN_PRICE, download
from systematic_rules import build_switch

START_DL = "1999-01-01"
START = "2001-01-02"          # SMH needs 200 days of history for its average
PERIODS = {"2001_2026": ("2001-01-02", None), "2001_2008": ("2001-01-02", "2008-12-31"),
           "2009_2017": ("2009-01-02", "2017-12-29"), "2018_2026": ("2018-01-02", None),
           "2000s_crash_2001_2002": ("2001-01-02", "2002-12-31"), "gfc_2007_2009": ("2007-06-01", "2009-06-30")}


def stats(nav: pd.Series, a=None, b=None) -> dict:
    s = nav.loc[a:b].dropna()
    s = s / s.iloc[0]
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    r = s.pct_change().dropna()
    cagr = float(s.iloc[-1] ** (1 / yrs) - 1)
    dd = float((s / s.cummax() - 1).min())
    return {"cagr": round(cagr, 4), "max_dd": round(dd, 4), "calmar": round(cagr / -dd, 2) if dd < 0 else None,
            "sharpe": round(float(r.mean() / r.std() * np.sqrt(252)), 2) if r.std() > 0 else None,
            "total": round(float(s.iloc[-1] - 1), 3)}


def main() -> None:
    u = pd.read_csv(OUT / "broad_universe.csv")
    u = u[u["bucket"].isin(PHYS)]
    broad_research.START_DL = START_DL
    close, vol = download(u["ticker"].tolist() + ["SPY", "SMH", "QQQ"])
    tick = [t for t in u["ticker"] if t in close.columns and close[t].notna().sum() > 260]
    cal = close["SPY"].dropna().index
    px = close.reindex(cal).ffill(limit=5)
    px = px.where(px > 0)
    dv = (close * vol).reindex(cal).rolling(60, min_periods=40).mean()
    liquid = ((px[tick] >= MIN_PRICE) & (dv[tick] >= 100e6)).fillna(False)
    print("first SMH", px["SMH"].first_valid_index(), "names with prices in 2001:",
          int(px.loc["2001-01-02", tick].notna().sum()), "liquid in 2001:", int(liquid.loc["2001-01-02"].sum()), flush=True)

    S = build_switch(px, liquid, tick, start=START)
    idx = S["idx"]
    navs = {"SWITCH": S["switch_trend"], "SMH_TREND": S["smh_trend"], "ROTATION": S["h_park"], "SMH": S["smh"],
            "QQQ": (px["QQQ"].reindex(idx) / px["QQQ"].reindex(idx).iloc[0])}
    res = {k: {p: stats(v, a, b) for p, (a, b) in PERIODS.items()} for k, v in navs.items()}
    yearly = pd.DataFrame({k: v.resample("YE").last().pct_change() for k, v in navs.items()})
    first = pd.DataFrame({k: [v.resample("YE").last().iloc[0] / v.iloc[0] - 1] for k, v in navs.items()},
                         index=[yearly.index[0]])
    yearly = yearly.fillna(first).round(4)
    yearly.index = yearly.index.year
    worst = {k: {"year": int(yearly[k].idxmin()), "return": float(yearly[k].min())} for k in yearly}
    beat = {k: f"{int((yearly[k] > yearly['SMH']).sum())}/{len(yearly)}" for k in yearly if k != "SMH"}
    held = S["pick_t"].value_counts(normalize=True).round(3).to_dict()
    held_by_era = {p: S["pick_t"].loc[a:b].value_counts(normalize=True).round(3).to_dict()
                   for p, (a, b) in PERIODS.items() if p in ("2001_2008", "2009_2017", "2018_2026")}
    liq_count = liquid.sum(axis=1).resample("YE").mean().round(0)
    liq_count.index = liq_count.index.year
    out = {"results": res, "worst_year": worst, "years_beating_smh": beat, "time_in_state": held,
           "time_in_state_by_era": held_by_era, "liquid_names_avg_by_year": liq_count.to_dict(),
           "limits": ["stock list = today's listings: survivor-biased before 2021, most in 2000-2008",
                      "SMH_TREND is free of that bias (SMH only)",
                      "$100M/day liquidity bar is nominal: fewer names qualified in early years"]}
    (OUT / "long_history_summary.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    yearly.to_csv(OUT / "long_history_yearly.csv", index_label="year")
    print(json.dumps(out, indent=1, default=str))
    print(yearly)


if __name__ == "__main__":
    main()
