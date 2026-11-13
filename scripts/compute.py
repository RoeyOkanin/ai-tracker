"""Daily live run: scores every layer and stock, runs the paper portfolio from
live_start, logs every decision, and writes docs/data/* for the dashboard."""
from __future__ import annotations

import csv
import json
import math
import os
from datetime import datetime, timezone

import pandas as pd
from pandas.tseries.offsets import BDay, BMonthEnd

from engine import (DATA, DOCS_DATA, STAGES_HE, composite_history, composite_score, is_tradable, layer_members,
                    layer_names, layer_stage, load_config, load_prices, pick_targets, prepare, regime_at, simulate)

REASON_HE = {
    "trailing_stop": "נשבר הסטופ הנגרר",
    "below_ma200": "נסגרה מתחת לממוצע 200",
    "profit_take": "קפיצה חדה בשבוע: מימוש שליש",
    "rebalance_out": "יוצאת באיזון החודשי",
    "rebalance_in": "נכנסת באיזון החודשי",
    "rebalance_add": "מוגדלת באיזון החודשי",
    "rebalance_trim": "מוקטנת באיזון החודשי",
}
REGIME_HE = {"green": "ירוק: המחזור מאיץ", "yellow": "צהוב: תמונה מעורבת", "red": "אדום: המחזור מאט"}
NEWS_LABEL_HE = {"confirmed": "מועמד מאושר לצוואר בקבוק: גם החדשות וגם המחיר",
                 "early": "מועמד מוקדם: החדשות מקדימות את המחיר",
                 "easing": "סימני הקלה: זמן לשקול לשחרר"}
LOG_FIELDS = ["logged_utc", "signal_date", "type", "ticker", "layer", "target_weight", "reason", "price_at_signal"]


def num(x, nd: int = 4):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if math.isfinite(f) else None


def rank_int(x):
    v = num(x, 0)
    return int(v) if v is not None else None


def iso(x) -> str | None:
    return None if x is None or pd.isna(x) else str(pd.Timestamp(x).date())


def append_log(rows: list[dict]) -> None:
    """Append-only record of what the system said, when it said it."""
    path = DATA / "decisions_log.csv"
    seen = set()
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                seen.add((r["signal_date"], r["type"], r["ticker"]))
    new = [r for r in rows if (r["signal_date"], r["type"], r["ticker"]) not in seen]
    if not new:
        return
    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if write_header:
            w.writeheader()
        for r in new:
            w.writerow(r)


def plan_rows(plan: dict, px, kind: str, now: str) -> list[dict]:
    d = plan["date"]
    rows = [{"logged_utc": now, "signal_date": iso(d), "type": kind, "ticker": t, "layer": plan["layer_of"][t],
             "target_weight": num(w, 4), "reason": "", "price_at_signal": num(px.at[d, t], 4)}
            for t, w in plan["targets"].items()]
    if not rows:  # an all-cash decision is a decision too
        rows = [{"logged_utc": now, "signal_date": iso(d), "type": kind, "ticker": "CASH", "layer": "",
                 "target_weight": 1.0, "reason": plan["regime"]["status"], "price_at_signal": None}]
    return rows


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    uni, rules = load_config()
    px = load_prices(uni)
    ind, lidx, lind = prepare(px, uni)
    d = px.index[-1]
    names, members = layer_names(uni), layer_members(uni)
    radar_path = DOCS_DATA / "radar.json"
    radar = json.loads(radar_path.read_text(encoding="utf-8")) if radar_path.exists() else None
    news_by_layer = {x["key"]: x for x in (radar or {}).get("layers", [])}
    news_by_stock = (radar or {}).get("stocks", {})
    prev_path = DOCS_DATA / "latest.json"
    prev_labels = {}
    if prev_path.exists():
        try:
            prev_labels = {x["key"]: x.get("news_label") for x in json.loads(prev_path.read_text(encoding="utf-8"))["layers"]}
        except (ValueError, KeyError):
            prev_labels = {}
    smh_w = {str(k): float(v) for k, v in (uni.get("smh_weights") or {}).items()}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def ago(n: int):
        return px.index[max(0, len(px.index) - 1 - n)]

    # ---- layers
    lscore = composite_history(lind, lidx.columns)
    lrank = lscore.rank(axis=1, ascending=False, method="min")
    layers_out = []
    for L in lidx.columns:
        p, m = lidx.at[d, L], lind["ma200"].at[d, L]
        above = bool(p > m) if pd.notna(p) and pd.notna(m) else None
        stage = layer_stage(lrank.at[d, L], lrank.at[ago(21), L], lrank.at[ago(63), L], above, lind["r1m"].at[d, L])
        layers_out.append({
            "key": L, "name": names.get(L, L), "stage": stage, "stage_label": STAGES_HE[stage],
            "rank": rank_int(lrank.at[d, L]), "rank_1w_ago": rank_int(lrank.at[ago(5), L]),
            "rank_1m_ago": rank_int(lrank.at[ago(21), L]), "rank_3m_ago": rank_int(lrank.at[ago(63), L]),
            "score": num(lscore.at[d, L], 3),
            **{k: num(lind[k].at[d, L]) for k in ("r1w", "r1m", "r3m", "r6m", "r12m")},
            "above_ma200": bool(p > m) if pd.notna(p) and pd.notna(m) else None,
            "dist_ma200": num(p / m - 1) if pd.notna(p) and pd.notna(m) else None,
            "members": members[L],
            "monitor_only": bool(uni["layers"][L].get("monitor_only")),
            "news": {k: news_by_layer.get(L, {}).get(k) for k in ("items7", "tight7", "ease7", "friction7", "net7", "net_prev7", "trend")},
        })
    layers_out.sort(key=lambda x: (x["rank"] is None, x["rank"] or 99))
    ranked = sorted([x for x in layers_out if (x["news"]["items7"] or 0) >= 3], key=lambda x: -(x["news"]["net7"] or 0))
    news_rank = {x["key"]: i + 1 for i, x in enumerate(ranked)}
    for x in layers_out:
        n, st = x["news"], x["stage"]
        net, trend, t7, e7 = (n["net7"] or 0), (n["trend"] or 0), (n["tight7"] or 0), (n["ease7"] or 0)
        label = None
        if net >= 3 and trend >= 0 and news_rank.get(x["key"], 99) <= 4 and st in ("heating", "leading"):
            label = "confirmed"
        elif net >= 3 and trend >= 2 and news_rank.get(x["key"], 99) <= 3 and st in ("cold", "neutral"):
            label = "early"
        elif e7 >= 3 and e7 > t7 and st in ("leading", "fading", "heating"):
            label = "easing"
        x["news_label"] = label
        x["news_label_he"] = NEWS_LABEL_HE.get(label)
        x["news_rank"] = news_rank.get(x["key"])

    # ---- stocks
    stocks_out = []
    for L, ts in members.items():
        avail = [t for t in ts if t in px.columns]
        sc = composite_score(ind, d, avail) if avail else pd.Series(dtype=float)
        for t in ts:
            card = (uni.get("companies") or {}).get(t, {})
            card_info = {"status": card.get("status", "active"), "exposure": card.get("exposure"), "why": card.get("why"),
                         "company": card.get("name")}
            if t not in px.columns or pd.isna(px.at[d, t]):
                stocks_out.append({"ticker": t, "layer": L, "layer_name": names[L], "missing": True, **card_info})
                continue
            p = px.at[d, t]
            ma50, ma200, hi = ind["ma50"].at[d, t], ind["ma200"].at[d, t], ind["high52"].at[d, t]
            stocks_out.append({
                "ticker": t, "layer": L, "layer_name": names[L], "tradable": is_tradable(uni, t),
                "price": num(p, 2), **{k: num(ind[k].at[d, t]) for k in ("r1w", "r1m", "r3m", "r6m", "r12m")},
                "dist_ma50": num(p / ma50 - 1) if pd.notna(ma50) else None,
                "dist_ma200": num(p / ma200 - 1) if pd.notna(ma200) else None,
                "above_ma200": bool(p > ma200) if pd.notna(ma200) else None,
                "vol": num(ind["vol"].at[d, t]), "from_52w_high": num(p / hi - 1) if pd.notna(hi) else None,
                "score_in_layer": num(sc.get(t), 3),
                "smh_weight": smh_w.get(t),
                **card_info,
                "news7": news_by_stock.get(t),
                "stretched": bool(pd.notna(ind["r1w"].at[d, t]) and pd.notna(ma50)
                                  and ind["r1w"].at[d, t] >= rules["profit_take"]["week_gain"]
                                  and p >= ma50 * (1 + rules["profit_take"]["above_ma50"])),
            })

    # ---- how concentrated is the bottleneck? (top-3 layers vs the median layer, 6 months)
    r6 = lind["r6m"][lidx.columns]
    spread = (r6.apply(lambda row: row.nlargest(3).mean() - row.median() if row.notna().sum() >= 6 else float("nan"), axis=1)
              .dropna())
    concentration = {
        "spread_6m": num(spread.iloc[-1]) if len(spread) else None,
        "percentile": num((spread <= spread.iloc[-1]).mean()) if len(spread) else None,
    }

    # ---- regime + "if the month ended today"
    reg, reg_1w = regime_at(px, ind, d, uni, rules), regime_at(px, ind, ago(5), uni, rules)
    preview = pick_targets(d, px, ind, lidx, lind, uni, rules)

    # ---- paper portfolio
    live_start = pd.Timestamp(rules["live_start"])
    log_rows: list[dict] = []
    if d >= live_start:
        sim = simulate(px, uni, rules, live_start, prepared=(ind, lidx, lind))
        navdf = sim["nav"]
        bench = px[rules["regime"]["benchmark"]]
        first = navdf.index[0]
        nav_chart = pd.DataFrame({"portfolio": navdf["nav"] / navdf["nav"].iloc[0] * 100,
                                  "SMH": bench.loc[first:] / bench.loc[first] * 100})
        nav_chart.round(3).to_csv(DOCS_DATA / "nav.csv", index_label="date")
        trades = sim["trades"]
        if len(trades):
            trades.to_csv(DATA / "live_trades.csv", index=False, float_format="%.6f")
        pend = sim["pending_rebalance"]
        if pend is not None:
            log_rows += plan_rows(pend, px, "rebalance", now)
        for t, e in sim["pending_exits"].items():
            log_rows.append({"logged_utc": now, "signal_date": iso(d), "type": "exit" if e["kind"] == "all" else "profit_take",
                             "ticker": t, "layer": next((p["layer"] for p in sim["positions"] if p["ticker"] == t), ""),
                             "target_weight": 0.0 if e["kind"] == "all" else None, "reason": e["reason"],
                             "price_at_signal": num(px.at[d, t], 4)})
        portfolio = {
            "status": "live", "start": iso(live_start),
            "return": num(navdf["nav"].iloc[-1] - 1), "bench_return": num(bench.loc[d] / bench.loc[first] - 1),
            "cash_weight": num(navdf["cash"].iloc[-1] / navdf["nav"].iloc[-1]),
            "positions": [{**p, "name": names.get(p["layer"], p["layer"]),
                           "entry_date": iso(p["entry_date"]),
                           **{k: num(p[k]) for k in ("weight", "entry_px", "price", "pnl", "peak", "stop_pct", "stop_level", "dist_to_stop")}}
                          for p in sorted(sim["positions"], key=lambda x: -x["weight"])],
            "orders_next_close": (
                [{"ticker": t, "action": "sell_all" if e["kind"] == "all" else "sell_third",
                  "reason": REASON_HE.get(e["reason"], e["reason"])} for t, e in sim["pending_exits"].items()]
                + ([{"ticker": t, "action": "target", "weight": num(w), "reason": "איזון חודשי"}
                    for t, w in pend["targets"].items()] if pend is not None else [])
            ),
            "rebalances": [{"signal_date": iso(r["signal_date"]), "exec_date": iso(r["exec_date"]),
                            "regime": r["regime"], "exposure": r["exposure"],
                            "layers": [names.get(L, L) for L in r["layers"]],
                            "targets": {t: num(w) for t, w in r["targets"].items()}}
                           for r in sim["rebalances"][-12:]],
        }
    else:
        portfolio = {"status": "not_started", "start": iso(live_start),
                     "planned_layers": [names.get(L, L) for L in preview["layers"]],
                     "planned_targets": {t: num(w) for t, w in preview["targets"].items()}}
        if d + BDay(1) >= live_start:   # last close before the start: this is the first real decision
            log_rows += plan_rows(preview, px, "initial", now)
    append_log(log_rows)

    # ---- target book: what the account should look like after the next close (read by execute.py)
    book = {"signal_date": iso(d), "generated_utc": now, "regime": reg["status"],
            "rebalance_band": rules["portfolio"]["rebalance_band"], "mode": "none", "targets": {}, "exits": [],
            "layer_of": {}}
    if portfolio["status"] == "live":
        cur = {p["ticker"]: p for p in sim["positions"]}
        base = {t: float(p["weight"]) for t, p in cur.items()}
        book["layer_of"] = {t: p["layer"] for t, p in cur.items()}
        for t, e in sim["pending_exits"].items():
            if e["kind"] == "all":
                base.pop(t, None)
                book["exits"].append({"ticker": t, "reason": e["reason"]})
            elif t in base:
                base[t] *= 1 - float(e["fraction"])
        if pend is not None:
            book["mode"] = "rebalance"
            book["targets"] = {t: round(float(w), 6) for t, w in pend["targets"].items()}
            book["current_weights"] = {t: round(w, 6) for t, w in base.items()}
            book["layer_of"].update(pend["layer_of"])
        else:
            book["mode"] = "hold"
            book["targets"] = {t: round(w, 6) for t, w in base.items()}
    elif d + BDay(1) >= live_start:
        book["mode"] = "initial"
        book["targets"] = {t: round(float(w), 6) for t, w in preview["targets"].items()}
        book["layer_of"] = dict(preview["layer_of"])
    (DOCS_DATA / "target_book.json").write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- alerts
    alerts = []
    if reg["status"] != reg_1w["status"]:
        alerts.append(f"מצב השוק השתנה השבוע: {REGIME_HE[reg_1w['status']]} ← {REGIME_HE[reg['status']]}")
    for L in lidx.columns:
        a_now = lidx.at[d, L] > lind["ma200"].at[d, L]
        a_then = lidx.at[ago(5), L] > lind["ma200"].at[ago(5), L]
        if pd.notna(lind["ma200"].at[d, L]) and pd.notna(lind["ma200"].at[ago(5), L]) and a_now != a_then:
            alerts.append(f"{names[L]}: {'עלתה מעל ' if a_now else 'ירדה מתחת ל'}ממוצע 200 השבוע")
        r_now, r_1m = lrank.at[d, L], lrank.at[ago(21), L]
        if pd.notna(r_now) and pd.notna(r_1m) and abs(r_1m - r_now) >= 4:
            alerts.append(f"{names[L]}: {'קפצה' if r_now < r_1m else 'צנחה'} מהמקום {int(r_1m)} למקום {int(r_now)} בחודש האחרון")
    if portfolio["status"] == "live":
        for o in portfolio["orders_next_close"]:
            if o["action"] in ("sell_all", "sell_third"):
                alerts.append(f"פקודה לסגירה הבאה: {o['ticker']}, {o['reason']}")
        held = {p["ticker"] for p in portfolio["positions"]}
        for s in stocks_out:
            if s.get("stretched") and s["ticker"] in held:
                alerts.append(f"{s['ticker']} מתוחה (קפיצה חדה בשבוע): לא מוכרים, אבל גם לא מוסיפים עכשיו")

    # ---- notification (the workflow turns this into a GitHub issue = email + app push)
    notify: list[str] = []
    if portfolio["status"] == "live" and portfolio["orders_next_close"]:
        notify.append(f"### פקודות לביצוע בסגירה הבאה (נתונים לסגירה של {iso(d)})")
        for o in portfolio["orders_next_close"]:
            act = {"sell_all": "מכירה מלאה", "sell_third": "מכירת שליש"}.get(o["action"], f"משקל יעד {round((o.get('weight') or 0) * 100, 1)}%")
            notify.append(f"- **{o['ticker']}**: {act} ({o['reason']})")
    if portfolio["status"] == "not_started" and d + BDay(1) >= live_start:
        notify.append(f"### תוכנית פתיחה לתיק, ביצוע בסגירה של {iso(live_start)}")
        notify.append(f"מצב השוק: {REGIME_HE[reg['status']]}, להשקיע {round(reg['exposure'] * 100)}% מהסכום שהקצית")
        for t, w in preview["targets"].items():
            notify.append(f"- **{t}** ({names.get(preview['layer_of'][t], '')}): {round(w * 100, 1)}%")
    reg_prev = regime_at(px, ind, ago(1), uni, rules)
    if reg_prev["status"] != reg["status"]:
        notify.append(f"### מצב השוק השתנה: {REGIME_HE[reg_prev['status']]} ← {REGIME_HE[reg['status']]}")
        notify.append(f"חשיפה לפי החוקים: {round(reg['exposure'] * 100)}% (ייושם בהחלטה החודשית הבאה)")
    radar_lines = []
    for x in layers_out:
        if x["news_label"] and x["news_label"] != prev_labels.get(x["key"]):
            n = x["news"]
            line = (f"{x['name']}: {x['news_label_he']} (חדשות 7 ימים: {n['tight7']} סימני מחסור, {n['ease7']} סימני הקלה; "
                    f"שלב מחיר: {STAGES_HE[x['stage']].split(':')[0]})")
            alerts.append(line)
            radar_lines.append(f"- {line}")
    if radar_lines:
        notify += ["### מכ\"ם צוואר בקבוק: שינוי בחדשות"] + radar_lines
    if notify and os.environ.get("NOTIFY_PATH"):
        notify.append("\nדשבורד: https://roeyokanin.github.io/ai-tracker/")
        with open(os.environ["NOTIFY_PATH"], "w", encoding="utf-8") as f:
            f.write("\n".join(notify) + "\n")

    decision_day = BMonthEnd().rollforward(d)
    latest = {
        "as_of": iso(d),
        "generated_utc": now,
        "regime": {**{k: (num(v) if isinstance(v, float) else v) for k, v in reg.items()},
                   "label": REGIME_HE[reg["status"]]},
        "bottleneck_concentration": concentration,
        "next_decision_close": iso(decision_day),
        "next_execution": iso(decision_day + BDay(1)),
        "layers": layers_out,
        "stocks": stocks_out,
        "if_month_ended_today": {
            "layers": [names.get(L, L) for L in preview["layers"]],
            "targets": {t: num(w) for t, w in preview["targets"].items()},
        },
        "portfolio": portfolio,
        "alerts": alerts,
        "news_radar": {"as_of": (radar or {}).get("as_of"), "generated_utc": (radar or {}).get("generated_utc"),
                       "sources_ok": (radar or {}).get("sources_ok")},
        "smh_weights_as_of": uni.get("smh_weights_as_of"),
    }
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    (DOCS_DATA / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- chart data: last 2 years of layer indices (100 = start of window) and daily ranks
    win = lidx.loc[ago(504):].copy()
    base = win.apply(lambda s: s.dropna().iloc[0] if s.notna().any() else float("nan"))
    hist = win / base * 100
    smh = px["SMH"].loc[win.index]
    hist["SMH"] = smh / smh.dropna().iloc[0] * 100
    hist.round(2).to_csv(DOCS_DATA / "layers_history.csv", index_label="date")
    lrank.loc[ago(252):].to_csv(DOCS_DATA / "layer_ranks.csv", index_label="date", float_format="%.0f")

    px.iloc[-460:].round(2).to_csv(DOCS_DATA / "prices_1y.csv", index_label="date")
    print(f"{iso(d)} | {REGIME_HE[reg['status']]} | top: {[x['name'] for x in layers_out[:3]]} | alerts: {len(alerts)}")


if __name__ == "__main__":
    main()
