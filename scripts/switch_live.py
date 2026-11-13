"""Nightly run of the main strategy: the switch (cash version).

Rules (tested in systematic_rules.py, decision frequency in freq_test.py):
  - Universe: every US-listed physical AI-chain stock (data/research/broad_universe.csv),
    tradable only with >= $100M average daily volume and price >= $5.
  - Rotation: at each month-end, the 6 strongest by momentum (3m, 6m, 12-1m) that are above
    their 200-day average; daily exits on trailing stop / 2% below the 200-day average.
    Money the rotation doesn't use sits in SMH.
  - Switch, at each month-end: rotation if it beat SMH over the last 6 months, else SMH.
  - Daily: when SMH would be held and SMH closes 2% below its 200-day average -> cash (T-bills);
    back to SMH when it closes above the average.
  - Every decision is taken on a close and executed at the next close.

Writes:
  docs/data/switch.json              what the dashboard shows
  docs/data/switch_target_book.json  the account after the next close (same schema execute.py reads)
  data/switch/decisions_log.csv      append-only, one row per trading day, never rewritten
"""
from __future__ import annotations

import csv
import json
import math
import os
from datetime import datetime, timezone

import pandas as pd
import yaml

from broad_research import MIN_PRICE
from engine import DATA, DOCS_DATA, ROOT, _is_decision_day, _next_trading_day
from systematic_rules import build_switch, load_prices

OUT = DATA / "switch"
STATE_HE = {"H": "רוטציה: 6 המניות החזקות בשרשרת", "SMH": "SMH (תעודת סל של שבבים)", "CASH": "מזומן (T-bills)"}
LOG_FIELDS = ["logged_utc", "signal_date", "hold_now", "hold_next", "rotation_vs_smh_6m", "smh_vs_ma200",
              "targets", "exits"]


def num(x, nd=4):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if math.isfinite(f) else None


def iso(x):
    return None if x is None or pd.isna(x) else str(pd.Timestamp(x).date())


def append_log(row: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "decisions_log.csv"
    if path.exists():
        with path.open(encoding="utf-8") as f:
            if any(r["signal_date"] == row["signal_date"] for r in csv.DictReader(f)):
                return
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def main() -> None:
    rules = yaml.safe_load((ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))
    live_start = pd.Timestamp(rules.get("live_start", "2026-11-16"))
    px, dv, tick = load_prices()
    liquid_big = ((px[tick] >= MIN_PRICE) & (dv[tick] >= 100e6)).fillna(False)
    S = build_switch(px, liquid_big, tick)
    sim, idx, pick_t = S["sim"], S["idx"], S["pick_t"]
    d = idx[-1]
    hold_next = pick_t.iloc[-1]
    hold_now = pick_t.iloc[-2] if len(pick_t) > 1 else hold_next
    rel, smh_px, ma200 = S["rel"][d], S["smh_px"][d], S["ma200"][d]
    smh_dist = smh_px / ma200 - 1 if pd.notna(ma200) else None
    month_end = _is_decision_day(idx, d, "monthly")
    next_exec = _next_trading_day(idx, d)
    # next month-end close (approximate with the calendar; holidays shift it by a day at most)
    nxt_me = (pd.Timestamp(d) + pd.offsets.BMonthEnd(0 if not month_end else 1))

    # ---- what the account should hold after the next close
    targets, exits, layer_of = {}, [], {}
    if hold_next == "H":
        pend = sim["pending_rebalance"]
        if pend is not None:
            base = {t: float(w) for t, w in pend["targets"].items()}
        else:
            base = {p["ticker"]: float(p["weight"]) for p in sim["positions"]}
            for t, e in sim["pending_exits"].items():
                if e["kind"] == "all":
                    base.pop(t, None)
                    exits.append({"ticker": t, "reason": e["reason"]})
        targets = {t: w for t, w in base.items() if w > 0}
        rest = max(0.0, 1.0 - sum(targets.values()))
        if rest > 0.005:
            targets["SMH"] = rest
        layer_of = {t: "rotation" for t in targets}
        layer_of["SMH"] = "parking"
    elif hold_next == "SMH":
        targets, layer_of = {"SMH": 1.0}, {"SMH": "switch"}
    changed = hold_next != hold_now
    rebalance_today = changed or (hold_next == "H" and sim["pending_rebalance"] is not None)
    started = next_exec >= live_start
    book = {"strategy": "switch", "signal_date": iso(d), "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hold": hold_next, "rebalance_band": 0.05,
            "mode": ("initial" if started and next_exec == live_start else
                     "rebalance" if started and rebalance_today else "hold" if started else "none"),
            "targets": {t: round(w, 6) for t, w in targets.items()}, "exits": exits, "layer_of": layer_of}
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    (DOCS_DATA / "switch_target_book.json").write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- paper portfolio from live_start (same daily series the backtest uses)
    nav = S["switch_trend"]
    paper = {"start": iso(live_start), "status": "pending"}
    if d >= live_start:
        base_d = idx[idx < live_start][-1]
        smh = S["smh"]
        paper = {"start": iso(live_start), "status": "live",
                 "return": num(nav[d] / nav[base_d] - 1), "smh_return": num(smh[d] / smh[base_d] - 1),
                 "max_drawdown": num(float((nav.loc[base_d:] / nav.loc[base_d:].cummax() - 1).min()))}
    hist = nav.loc[d - pd.Timedelta(days=400):]
    smh_hist = S["smh"].reindex(hist.index)

    # ---- why
    if hold_next == "H":
        why = f"הרוטציה עשתה {rel * 100:+.0f}% יותר מ-SMH ב-6 החודשים האחרונים, לכן מריצים אותה."
    elif hold_next == "SMH":
        why = f"הרוטציה פיגרה אחרי SMH ב-{abs(rel) * 100:.0f}% ב-6 חודשים, ו-SMH מעל ממוצע 200: מחזיקים SMH."
    else:
        why = (f"הרוטציה לא מובילה, ו-SMH נמצא {abs(smh_dist) * 100:.1f}% מתחת לממוצע 200: יושבים במזומן "
               "עד ש-SMH ייסגר מעל הממוצע.")
    positions = []
    if hold_next == "H" or hold_now == "H":
        for p in sim["positions"]:
            positions.append({"ticker": p["ticker"], "weight": num(p["weight"], 3), "pnl": num(p["pnl"], 3),
                              "entry_date": iso(p["entry_date"]), "stop_level": num(p["stop_level"], 2),
                              "dist_to_stop": num(p["dist_to_stop"], 3)})
    out = {
        "as_of": iso(d), "next_execution": iso(next_exec), "next_monthly_decision": iso(nxt_me),
        "hold_now": hold_now, "hold_next": hold_next, "hold_next_he": STATE_HE[hold_next], "changed": bool(changed),
        "why": why, "rotation_vs_smh_6m": num(rel), "smh_vs_ma200": num(smh_dist),
        "targets": book["targets"], "exits": exits, "rotation_positions": positions,
        "paper": paper,
        "history": {"dates": [iso(x) for x in hist.index[::5]],
                    "switch": [num(v / hist.iloc[0], 4) for v in hist.iloc[::5]],
                    "smh": [num(v / smh_hist.iloc[0], 4) for v in smh_hist.iloc[::5]]},
        "rules_he": [
            "בסוף כל חודש: אם הרוטציה עשתה יותר מ-SMH ב-6 החודשים האחרונים, מריצים רוטציה. אחרת SMH.",
            "רוטציה = 6 המניות החזקות בשרשרת הפיזית (3, 6 ו-12 חודשים), רק מעל ממוצע 200, מחזור מעל $100M ליום.",
            "כל יום: סטופ נגרר (10%-25%) וסגירה 2% מתחת לממוצע 200 = מכירה למחרת.",
            "כל יום: אם צריך להחזיק SMH ו-SMH נסגר 2% מתחת לממוצע 200, עוברים למזומן. חוזרים כשהוא נסגר מעליו.",
            "כסף שהרוטציה לא משתמשת בו יושב ב-SMH.",
        ],
    }
    (DOCS_DATA / "switch.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    append_log({"logged_utc": book["generated_utc"], "signal_date": iso(d), "hold_now": hold_now, "hold_next": hold_next,
                "rotation_vs_smh_6m": num(rel), "smh_vs_ma200": num(smh_dist),
                "targets": json.dumps(book["targets"]), "exits": json.dumps(exits)})

    note = os.environ.get("NOTIFY_PATH")
    if note and (changed or exits or (hold_next == "H" and sim["pending_rebalance"] is not None)):
        lines = [f"### המתג: {STATE_HE[hold_now]} ← {STATE_HE[hold_next]}" if changed else "### המתג: שינוי בתיק",
                 why, "", "| מניה | משקל יעד |", "|---|---|"]
        lines += [f"| {t} | {w * 100:.1f}% |" for t, w in sorted(book["targets"].items(), key=lambda x: -x[1])]
        lines += [f"- יציאה: {e['ticker']} ({e['reason']})" for e in exits]
        lines.append(f"\nביצוע בסגירה של {iso(next_exec)}.")
        with open(note, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n\n")
    print(json.dumps({k: out[k] for k in ("as_of", "hold_now", "hold_next", "why", "targets", "paper")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
