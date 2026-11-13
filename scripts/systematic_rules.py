"""One systematic rule set, SMH as the default when there is no clear edge.

Candidates (all parameters fixed before the run, nothing tuned):
  SMH            buy & hold SMH
  SMH_TREND      SMH; to cash when SMH closes 2% below its 200-day average, back when above it
  H_CASH         version H (physical chain, 6 strongest, monthly, trailing stop, MA200 exit,
                 market filter) with unused money in cash  -- what we tested so far
  H_PARK         the same, but every dollar H does not use sits in SMH
  CORE_70_30     70% SMH + 30% H_PARK, back to 70/30 once a year
  SWITCH         each month-end: hold H_PARK if it beat SMH over the last 6 months, else SMH
  SWITCH_TREND   SWITCH, but when SMH is the pick and SMH is 2% below its 200-day average -> cash

Honest check against picking the best of 7 in hindsight ("walk-forward"):
  every January from 2021, take the candidate with the best Sharpe over the previous
  3 years and hold it for that year. The chained result is what someone following
  "use whatever has worked" would really have earned.

Every decision is made on a close and executed on the next close; 0.15% per side.

Usage (GitHub Actions): python scripts/systematic_rules.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from broad_research import BENCH, MIN_DOLLAR_VOL, MIN_PRICE, download, make_uni, run_variant
from bottleneck_research import IS_END, IS_START, OOS_START, OUT, PHYS, RAW
from engine import load_config, merge_rules, perf_stats, yearly_returns

COST = 0.0015
LOOKBACK = 126          # 6 months, for SWITCH
WF_YEARS = 3            # walk-forward look-back


def load_prices():
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
    return px, dv, tick


def month_end_flags(idx: pd.DatetimeIndex) -> pd.Series:
    nxt = pd.Series(idx, index=idx).shift(-1)
    return pd.Series([n is pd.NaT or pd.isna(n) or n.month != d.month for d, n in zip(idx, nxt)], index=idx)


def from_signal(rets: dict[str, pd.Series], choice: pd.Series) -> pd.Series:
    """choice[d] = which sleeve to hold from the NEXT close on. Switching costs 2 x 0.15%."""
    idx = choice.index
    held = choice.shift(1)              # decided at close d, earns from d+1
    r = pd.Series(0.0, index=idx)
    for k, s in rets.items():
        r = r.where(held != k, s.reindex(idx).fillna(0.0))
    switches = (held != held.shift(1)) & held.shift(1).notna()
    r = r - switches.astype(float) * 2 * COST
    r.iloc[0] = 0.0
    return (1 + r).cumprod()


def mix_yearly(a: pd.Series, b: pd.Series, wa: float) -> pd.Series:
    idx = a.index.intersection(b.index)
    ra, rb = a.reindex(idx).pct_change().fillna(0), b.reindex(idx).pct_change().fillna(0)
    va, vb, prev, out = wa, 1 - wa, None, []
    for d in idx:
        if prev is not None and d.year != prev:
            t = va + vb
            moved = abs(va - t * wa)
            va, vb = t * wa, t * (1 - wa)
            va -= moved * COST
            vb -= moved * COST
        va *= 1 + ra[d]
        vb *= 1 + rb[d]
        prev = d.year
        out.append(va + vb)
    return pd.Series(out, index=idx)


def main() -> None:
    px, dv, tick = load_prices()
    liquid_big = ((px[tick] >= MIN_PRICE) & (dv[tick] >= 100e6)).fillna(False)
    _, rules = load_config()
    uni = make_uni({t: [t] for t in tick}, {})
    r_h = merge_rules(rules, {"portfolio": {"layers_to_hold": 6, "stocks_per_layer": 1, "keep_if_rank_at_most": 15,
                                            "max_weight": 0.30}})
    sim = run_variant(px, liquid_big, uni, r_h, IS_START)
    h = sim["nav"]
    idx = h.index

    smh_px = px["SMH"].reindex(idx)
    smh_r = smh_px.pct_change().fillna(0.0)
    smh = (1 + smh_r).cumprod()
    ma200 = px["SMH"].rolling(200, min_periods=200).mean().reindex(idx)

    # SMH with a trend exit (state machine: out below MA200 -2%, back in above MA200)
    state, st = [], "SMH"
    for d in idx:
        p, m = smh_px[d], ma200[d]
        if pd.notna(m):
            if st == "SMH" and p < m * 0.98:
                st = "CASH"
            elif st == "CASH" and p > m:
                st = "SMH"
        state.append(st)
    trend_state = pd.Series(state, index=idx)
    cash_r = pd.Series(0.0, index=idx)
    smh_trend = from_signal({"SMH": smh_r, "CASH": cash_r}, trend_state)

    h_cash = h["nav"] / h["nav"].iloc[0]
    h_r = h_cash.pct_change().fillna(0.0)
    idle = (1 - h["invested"]).clip(0, 1).shift(1).fillna(1.0)
    park_cost = (1 - h["invested"]).clip(0, 1).diff().abs().fillna(0.0) * COST
    h_park_r = h_r + idle * smh_r - park_cost
    h_park = (1 + h_park_r).cumprod()

    core = mix_yearly(smh, h_park, 0.7)

    me = month_end_flags(idx)
    rel = (h_park / h_park.shift(LOOKBACK)) - (smh / smh.shift(LOOKBACK))
    pick, cur = [], "SMH"
    for d in idx:
        if me[d] and pd.notna(rel[d]):
            cur = "H" if rel[d] > 0 else "SMH"
        pick.append(cur)
    pick = pd.Series(pick, index=idx)
    switch = from_signal({"H": h_park_r, "SMH": smh_r}, pick)
    pick_t = pick.where(~((pick == "SMH") & (trend_state == "CASH")), "CASH")
    switch_trend = from_signal({"H": h_park_r, "SMH": smh_r, "CASH": cash_r}, pick_t)

    cands = {"SMH": smh, "SMH_TREND": smh_trend, "H_CASH": h_cash, "H_PARK": h_park,
             "CORE_70_30": core, "SWITCH": switch, "SWITCH_TREND": switch_trend}

    # walk-forward: each January pick the best 3-year Sharpe, hold for the year
    rets = {k: v.pct_change().fillna(0.0) for k, v in cands.items()}
    wf_r, wf_pick = [], {}
    years = sorted(set(idx.year))
    for y in years:
        if y < idx[0].year + WF_YEARS:
            continue
        past = slice(pd.Timestamp(y - WF_YEARS, 1, 1), pd.Timestamp(y - 1, 12, 31))
        sh = {k: float(r.loc[past].mean() / r.loc[past].std()) for k, r in rets.items()}
        best = max(sh, key=sh.get)
        wf_pick[y] = {"chosen": best, "sharpe_3y": {k: round(v * np.sqrt(252), 2) for k, v in sh.items()}}
        seg = rets[best].loc[str(y)].copy()
        if wf_r and wf_pick.get(y - 1, {}).get("chosen") != best:
            seg.iloc[0] -= 2 * COST
        wf_r.append(seg)
    wf = (1 + pd.concat(wf_r)).cumprod()
    cands_wf = {k: v.loc[wf.index[0]:] / v.loc[wf.index[0]] for k, v in cands.items()}
    cands_wf["WALK_FORWARD"] = wf / wf.iloc[0]

    periods = {"calibration_2018_2022": (IS_START, IS_END), "out_of_sample_2023_2026": (OOS_START, None),
               "full_2018_2026": (IS_START, None)}
    res, yearly = {}, {}
    for k, nav in cands.items():
        for pk, (a, b) in periods.items():
            seg = nav.loc[a:b].dropna()
            res.setdefault(k, {})[pk] = {m: round(float(v), 4) for m, v in perf_stats(seg / seg.iloc[0]).items()}
        yearly[k] = yearly_returns(nav)
    wf_res = {k: {m: round(float(v), 4) for m, v in perf_stats(v).items()} for k, v in cands_wf.items()}
    yearly["WALK_FORWARD"] = yearly_returns(cands_wf["WALK_FORWARD"])
    ydf = pd.DataFrame(yearly)
    beat = {k: f"{int((ydf[k] > ydf['SMH']).sum())}/{int(ydf[k].notna().sum())}" for k in ydf.columns if k != "SMH"}

    # what each rule says today
    d = idx[-1]
    now = {"smh_vs_ma200": round(float(smh_px[d] / ma200[d] - 1), 4), "smh_trend_state": trend_state[d],
           "h_vs_smh_6m": round(float(rel[d]), 4), "switch_holds": pick[d], "switch_trend_holds": pick_t[d],
           "h_invested": round(float(h["invested"].iloc[-1]), 3),
           "h_positions": [{"ticker": p["ticker"], "weight": round(p["weight"], 3), "pnl": round(p["pnl"], 3)}
                           for p in sim["positions"]],
           "h_next_plan": (sorted(sim["pending_rebalance"]["targets"].items(), key=lambda x: -x[1])
                           if sim["pending_rebalance"] else None)}
    switches_per_year = round(float(((pick != pick.shift(1)).sum() - 1) / (len(idx) / 252)), 1)

    (OUT / "systematic_summary.json").write_text(json.dumps({
        "asof": str(d.date()), "results": res, "walk_forward_from": str(wf.index[0].date()),
        "walk_forward_results": wf_res, "walk_forward_picks": wf_pick, "years_beating_smh": beat,
        "switch_changes_per_year": switches_per_year, "now": now,
    }, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    ydf.to_csv(OUT / "systematic_yearly.csv", float_format="%.4f", index_label="year")
    pd.DataFrame(cands).to_csv(OUT / "systematic_nav.csv", float_format="%.5f", index_label="date")

    pd.set_option("display.width", 220)
    print(pd.DataFrame({k: {f"{pk[:3]}_{m}": v[pk][m] for pk in v for m in ("cagr", "max_drawdown", "sharpe")}
                        for k, v in res.items()}).T)
    print("walk-forward from", wf.index[0].date())
    print(pd.DataFrame(wf_res).T[["cagr", "max_drawdown", "sharpe"]])
    print({y: v["chosen"] for y, v in wf_pick.items()})
    print("years beating SMH:", beat)
    print((ydf * 100).round(1))
    print(json.dumps(now, indent=1, default=str))


if __name__ == "__main__":
    main()
