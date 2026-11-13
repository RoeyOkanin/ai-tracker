"""How often should the system decide?  monthly vs weekly vs daily.

Same rules as the recommended SWITCH (cash version) in systematic_rules.py; only the
decision frequency changes, for both the rotation's re-selection and the switch
between rotation / SMH / T-bills. Daily exits (trailing stop, MA200) are the same
in every variant. Costs 0.15% per side; trades per year reported (taxes not modelled:
in Israel every realized gain pays 25%, so more trades = more tax paid early).

Usage (GitHub Actions): python scripts/freq_test.py
"""
from __future__ import annotations

import json

import pandas as pd

from broad_research import MIN_PRICE, make_uni, run_variant
from bottleneck_research import IS_END, IS_START, OOS_START, OUT
from engine import _is_decision_day, load_config, merge_rules, perf_stats, yearly_returns
from systematic_rules import COST, LOOKBACK, from_signal, load_prices

FREQS = ["monthly", "weekly", "daily"]


def main() -> None:
    px, dv, tick = load_prices()
    liquid_big = ((px[tick] >= MIN_PRICE) & (dv[tick] >= 100e6)).fillna(False)
    _, rules = load_config()
    uni = make_uni({t: [t] for t in tick}, {})
    res, yearly = {}, {}
    periods = {"calibration_2018_2022": (IS_START, IS_END), "out_of_sample_2023_2026": (OOS_START, None),
               "full_2018_2026": (IS_START, None)}
    for f in FREQS:
        r = merge_rules(rules, {"portfolio": {"layers_to_hold": 6, "stocks_per_layer": 1, "keep_if_rank_at_most": 15,
                                              "max_weight": 0.30, "rebalance_freq": f}})
        sim = run_variant(px, liquid_big, uni, r, IS_START)
        h, idx = sim["nav"], sim["nav"].index
        years = (idx[-1] - idx[0]).days / 365.25
        h_trades = len(sim["trades"]) / years

        smh_px = px["SMH"].reindex(idx)
        smh_r = smh_px.pct_change().fillna(0.0)
        smh = (1 + smh_r).cumprod()
        ma200 = px["SMH"].rolling(200, min_periods=200).mean().reindex(idx)
        h_r = (h["nav"] / h["nav"].iloc[0]).pct_change().fillna(0.0)
        idle = (1 - h["invested"]).clip(0, 1).shift(1).fillna(1.0)
        park_cost = (1 - h["invested"]).clip(0, 1).diff().abs().fillna(0.0) * COST
        h_park_r = h_r + idle * smh_r - park_cost
        h_park = (1 + h_park_r).cumprod()
        rel = h_park / h_park.shift(LOOKBACK) - smh / smh.shift(LOOKBACK)

        pick, cur, trend = [], "SMH", "SMH"
        for d in idx:
            if _is_decision_day(idx, d, f):
                p_, m_ = smh_px[d], ma200[d]
                if pd.notna(m_):
                    if trend == "SMH" and p_ < m_ * 0.98:
                        trend = "CASH"
                    elif trend == "CASH" and p_ > m_:
                        trend = "SMH"
                if pd.notna(rel[d]):
                    cur = "H" if rel[d] > 0 else "SMH"
            pick.append("CASH" if (cur == "SMH" and trend == "CASH") else cur)
        pick = pd.Series(pick, index=idx)
        nav = from_signal({"H": h_park_r, "SMH": smh_r, "CASH": pd.Series(0.0, index=idx)}, pick)
        switches = int((pick != pick.shift(1)).sum() - 1)

        for name, series in ((f"SWITCH_TREND {f}", nav), (f"H alone {f}", h_park)):
            res[name] = {pk: {k: round(float(v), 4) for k, v in perf_stats(series.loc[a:b] / series.loc[a:b].iloc[0]).items()}
                         for pk, (a, b) in periods.items()}
            yearly[name] = yearly_returns(series)
        res[f"SWITCH_TREND {f}"]["activity"] = {"rotation_trades_per_year": round(h_trades, 1),
                                                "switches_per_year": round(switches / years, 1),
                                                "share_of_days_in_rotation": round(float((pick == "H").mean()), 3),
                                                "share_of_days_in_cash": round(float((pick == "CASH").mean()), 3)}
        print(f, {k: (v["full_2018_2026"]["cagr"], v["full_2018_2026"]["max_drawdown"]) for k, v in res.items()
                  if k.endswith(f)}, res[f"SWITCH_TREND {f}"]["activity"], flush=True)

    smh = px["SMH"].loc[IS_START:].dropna()
    res["SMH"] = {pk: {k: round(float(v), 4) for k, v in perf_stats(smh.loc[a:b] / smh.loc[a:b].iloc[0]).items()}
                  for pk, (a, b) in periods.items()}
    yearly["SMH"] = yearly_returns(smh / smh.iloc[0])
    (OUT / "freq_summary.json").write_text(json.dumps({"results": res}, indent=1, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame(yearly).to_csv(OUT / "freq_yearly.csv", float_format="%.4f", index_label="year")
    pd.set_option("display.width", 220)
    print(pd.DataFrame({k: {f"{pk[:3]}_{m}": v[pk][m] for pk in periods for m in ("cagr", "max_drawdown", "sharpe")}
                        for k, v in res.items()}).T)
    print((pd.DataFrame(yearly) * 100).round(1))


if __name__ == "__main__":
    main()
