"""Tests the exact live rules on history and compares them with simple alternatives.

Honest caveat printed with every run: the stock list was chosen in 2026, knowing
which companies became AI winners. That flatters every strategy that uses it,
so the fair test is the rotation vs. owning the same list equally.
"""
from __future__ import annotations

import json
import sys

import pandas as pd

from engine import (DATA, load_config, load_prices, merge_rules, perf_stats, prepare, simulate,
                    simulate_equal_weight, yearly_returns)

START = sys.argv[1] if len(sys.argv) > 1 else "2019-01-02"

VARIANTS = {
    "rotation (live rules)": {},
    "rotation, no market filter": {"regime": {"enabled": False}},
    "rotation, no stops / profit-take": {"exits": {"trailing_stop": False, "trend_exit": False},
                                         "profit_take": {"enabled": False}},
    "rotation, 2 layers": {"portfolio": {"layers_to_hold": 2}},
    "rotation, 4 layers": {"portfolio": {"layers_to_hold": 4}},
}


def main() -> None:
    uni, rules = load_config()
    px = load_prices(uni)
    prepared = prepare(px, uni)
    navs, extra = {}, {}
    for name, override in VARIANTS.items():
        sim = simulate(px, uni, merge_rules(rules, override), START, prepared=prepared)
        navs[name] = sim["nav"]["nav"]
        t = sim["trades"]
        years = (navs[name].index[-1] - navs[name].index[0]).days / 365.25
        extra[name] = {
            "trades_per_year": round(len(t) / years, 1) if len(t) else 0,
            "avg_invested": round(float(sim["nav"]["invested"].mean()), 3),
            "exit_reasons": t["reason"].value_counts().to_dict() if len(t) else {},
        }
        if name == "rotation (live rules)":
            base_sim = sim

    first = navs["rotation (live rules)"].index[0]
    navs["own the whole list equally"] = simulate_equal_weight(px, uni, rules, START)
    for b in ("SMH", "QQQ", "SPY"):
        navs[f"buy & hold {b}"] = px[b].loc[first:] / px[b].loc[first]

    table = {k: perf_stats(v) for k, v in navs.items()}
    for k in table:
        table[k].update(extra.get(k, {}))
    yearly = pd.DataFrame({k: yearly_returns(v) for k, v in navs.items()})

    out = DATA / "backtest"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(navs).to_csv(out / "nav.csv", float_format="%.5f", index_label="date")
    yearly.to_csv(out / "yearly.csv", float_format="%.4f", index_label="year")
    layers_held = pd.DataFrame([{"exec_date": r["exec_date"].date(), "regime": r["regime"], "exposure": r["exposure"],
                                 "layers": ", ".join(r["layers"]), "stocks": ", ".join(r["targets"])}
                                for r in base_sim["rebalances"]])
    layers_held.to_csv(out / "monthly_picks.csv", index=False)
    (out / "summary.json").write_text(json.dumps({"start": START, "end": str(px.index[-1].date()), "results": table},
                                                 indent=1, ensure_ascii=False, default=str), encoding="utf-8")

    pd.set_option("display.width", 200)
    cols = ["cagr", "vol", "sharpe", "max_drawdown", "worst_month", "pct_positive_months"]
    print(pd.DataFrame(table).T[cols].map(lambda x: f"{x:.2f}" if isinstance(x, float) else x))
    print()
    print((yearly * 100).round(1))
    print("\nCaveat: stock list picked in 2026 with hindsight -> all results are flattered.")


if __name__ == "__main__":
    main()
