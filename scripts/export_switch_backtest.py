"""Export the switch backtest in a small file the dashboard can read (docs/data/switch_backtest.json).

Reads the research output of systematic_rules.py (data/research/systematic_*.{csv,json}).
UI-only helper: no trading logic here. Run after the research workflow:
    python scripts/export_switch_backtest.py [research_dir]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "research"
OUT = ROOT / "docs" / "data" / "switch_backtest.json"


def r4(x):
    return None if pd.isna(x) else round(float(x), 4)


def main() -> None:
    nav = pd.read_csv(SRC / "systematic_nav.csv", parse_dates=["date"]).set_index("date")
    summ = json.loads((SRC / "systematic_summary.json").read_text(encoding="utf-8"))
    yearly = pd.read_csv(SRC / "systematic_yearly.csv")

    # what the switch held each day, read off its own returns: flat = cash, same as SMH = SMH, else rotation
    ret = nav.pct_change().fillna(0)
    held = pd.Series("H", index=nav.index)
    held[(ret["SWITCH_TREND"] - ret["SMH"]).abs() < 1e-7] = "S"
    held[ret["SWITCH_TREND"].abs() < 1e-9] = "C"
    held.iloc[0] = "S"

    wk = nav.resample("W-FRI").last().dropna()
    wk_held = held.resample("W-FRI").agg(lambda x: x.value_counts().idxmax() if len(x) else "S").reindex(wk.index).fillna("S")
    full = summ["results"]["SWITCH_TREND"]["full_2018_2026"]
    smh = summ["results"]["SMH"]["full_2018_2026"]
    out = {
        "as_of": str(nav.index[-1].date()),
        "dates": [str(d.date()) for d in wk.index],
        "switch": [r4(v) for v in wk["SWITCH_TREND"]],
        "smh": [r4(v) for v in wk["SMH"]],
        "held": list(wk_held),
        "stats": {"cagr": full["cagr"], "max_drawdown": full["max_drawdown"], "sharpe": full["sharpe"],
                  "smh_cagr": smh["cagr"], "smh_max_drawdown": smh["max_drawdown"],
                  "years_beating_smh": summ.get("years_beating_smh", {}).get("SWITCH_TREND"),
                  "switch_changes_per_year": summ.get("switch_changes_per_year")},
        "yearly": [{"year": int(r.year), "switch": r4(r.SWITCH_TREND), "smh": r4(r.SMH)} for r in yearly.itertuples()],
        "now": {"hold": summ.get("now", {}).get("switch_trend_holds"),
                "rotation_vs_smh_6m": summ.get("now", {}).get("h_vs_smh_6m"),
                "smh_vs_ma200": summ.get("now", {}).get("smh_vs_ma200")},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} ({len(out['dates'])} weeks, holds {out['now']['hold']})")


if __name__ == "__main__":
    main()
