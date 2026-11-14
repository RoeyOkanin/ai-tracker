"""Honest test: no hand-picked list.

The universe is every US-listed stock (NASDAQ / NYSE / AMEX, ADRs included) whose
*industry* belongs to the AI supply chain - chips, hardware, networking, electrical
and cooling equipment, power, construction, cloud, software. Nobody chose names.
On every month-end the system only sees stocks that were liquid *at that moment*
(price >= $5, 60-day average dollar volume >= $20M), so a company enters the
moment the market starts trading it seriously - the same way a future winner would.

Remaining bias (stated, not hidden): the symbol list is today's listings, so
companies that were delisted (bankrupt or acquired) since 2017 are missing.

Usage (GitHub Actions):  python scripts/broad_research.py
Local re-run on saved prices:  python scripts/broad_research.py --offline
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

import engine
from engine import DATA, load_config, merge_rules, perf_stats, prepare, simulate, yearly_returns

OUT = DATA / "research"
RAW = DATA / "broad"
START_DL = "2017-06-01"
SYMBOLS = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/{ex}/{ex}_full_tickers.json"
MIN_PRICE = 5.0
MIN_DOLLAR_VOL = 20e6
BENCH = ["SPY", "SMH", "QQQ"]

# industry -> AI-chain bucket. Defined by what the industry *is*, never by who won.
BUCKETS = {
    ("*", "Semiconductors"): "semis",
    ("Technology", "Industrial Machinery/Components"): "tech_equipment",   # chip tools, power & cooling gear
    ("Technology", "Electrical Products"): "hardware",
    ("*", "Computer Manufacturing"): "hardware",
    ("*", "Computer peripheral equipment"): "hardware",
    ("*", "Electronic Components"): "hardware",
    ("*", "Radio And Television Broadcasting And Communications Equipment"): "networking",
    ("*", "Computer Communications Equipment"): "networking",
    ("*", "Telecommunications Equipment"): "networking",
    ("Industrials", "Electrical Products"): "electrical",
    ("Energy", "Electrical Products"): "electrical",
    ("Industrials", "Industrial Machinery/Components"): "industrial_equipment",
    ("Energy", "Industrial Machinery/Components"): "industrial_equipment",
    ("*", "Electric Utilities: Central"): "power",
    ("*", "Power Generation"): "power",
    ("*", "Engineering & Construction"): "construction",
    ("*", "Water Sewer Pipeline Comm & Power Line Construction"): "construction",
    ("*", "EDP Services"): "cloud_services",
    ("*", "Computer Software: Programming Data Processing"): "cloud_services",
    ("*", "Computer Software: Prepackaged Software"): "software",
}
BUCKET_HE = {
    "semis": "שבבים", "tech_equipment": "ציוד טכנולוגי (כלי שבבים, חשמל וקירור)", "hardware": "חומרה ורכיבים",
    "networking": "רשתות ותקשורת", "electrical": "ציוד חשמל תעשייתי", "industrial_equipment": "מכונות תעשייה",
    "power": "ייצור חשמל", "construction": "בנייה ותשתיות", "cloud_services": "ענן ושירותי מידע",
    "software": "תוכנה",
}


# ---------------------------------------------------------------- universe
def build_universe() -> pd.DataFrame:
    rows = []
    for ex in ("nasdaq", "nyse", "amex"):
        with urllib.request.urlopen(SYMBOLS.format(ex=ex), timeout=60) as r:
            data = json.load(r)
        for x in data:
            sym = str(x.get("symbol", "")).strip()
            if not sym or "^" in sym or "/" in sym or " " in sym:
                continue
            sector, industry = x.get("sector") or "", x.get("industry") or ""
            b = BUCKETS.get((sector, industry)) or BUCKETS.get(("*", industry))
            if not b:
                continue
            try:
                mc = float(x.get("marketCap") or 0)
            except ValueError:
                mc = 0.0
            if mc < 50e6:          # shells / dead tickers only; no "big winners" filter
                continue
            rows.append({"ticker": sym.replace(".", "-"), "name": x.get("name", ""), "exchange": ex,
                         "sector": sector, "industry": industry, "bucket": b, "market_cap_now": mc})
    u = pd.DataFrame(rows).drop_duplicates("ticker").sort_values("ticker").reset_index(drop=True)
    return u


def download(tickers: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    import yfinance as yf
    closes, vols = [], []
    for i in range(0, len(tickers), 150):
        chunk = tickers[i:i + 150]
        for attempt in range(4):
            try:
                raw = yf.download(chunk, start=START_DL, auto_adjust=True, progress=False,
                                  group_by="column", threads=True)
                if raw is not None and not raw.empty:
                    c, v = raw["Close"], raw["Volume"]
                    if isinstance(c, pd.Series):
                        c, v = c.to_frame(chunk[0]), v.to_frame(chunk[0])
                    closes.append(c)
                    vols.append(v)
                    break
            except Exception as e:
                print(f"chunk {i}: {e}", file=sys.stderr)
            time.sleep(15 * (attempt + 1))
        print(f"downloaded {min(i + 150, len(tickers))}/{len(tickers)}", flush=True)
    close = pd.concat(closes, axis=1)
    vol = pd.concat(vols, axis=1)
    for f in (close, vol):
        f.index = pd.to_datetime([x.date() for x in f.index])
    close = close.loc[:, ~close.columns.duplicated()]
    vol = vol.loc[:, ~vol.columns.duplicated()]
    from engine import drop_partial_session
    return drop_partial_session(close), drop_partial_session(vol)


# ---------------------------------------------------------------- variants
def make_uni(groups: dict[str, list[str]], names: dict[str, str]) -> dict:
    return {
        "calendar": "SPY",
        "benchmarks": BENCH,
        "layers": {k: {"name": names.get(k, k), "tickers": v} for k, v in groups.items()},
        "signal_only": [],
    }


def run_variant(px, liquid, uni, rules, start):
    """Same engine as the live system; the only addition is that a stock that was
    not liquid on the decision day can't be bought."""
    orig = engine.pick_targets

    def pick(d, *a, exclude=None, **k):
        row = liquid.loc[d] if d in liquid.index else None
        bad = set(row.index[~row]) if row is not None else set()
        return orig(d, *a, exclude=set(exclude or ()) | bad, **k)

    engine.pick_targets = pick
    try:
        cols = [c for c in px.columns if c in set(engine.all_tickers(uni))]
        sub = px[cols]
        sim = simulate(sub, uni, rules, start, prepared=prepare(sub, uni))
    finally:
        engine.pick_targets = orig
    return sim


def main() -> None:
    offline = "--offline" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    if offline:
        u = pd.read_csv(OUT / "broad_universe.csv")
        close = pd.read_pickle(RAW / "close.pkl")
        vol = pd.read_pickle(RAW / "vol.pkl")
    else:
        u = build_universe()
        u.to_csv(OUT / "broad_universe.csv", index=False)
        print(f"universe: {len(u)} stocks", u["bucket"].value_counts().to_dict(), flush=True)
        close, vol = download(u["ticker"].tolist() + BENCH)
        close.to_pickle(RAW / "close.pkl")
        vol.to_pickle(RAW / "vol.pkl")

    tick = [t for t in u["ticker"] if t in close.columns and close[t].notna().sum() > 260]
    u = u[u["ticker"].isin(tick)]
    _, rules = load_config()

    cal = close["SPY"].dropna().index
    px = close.reindex(cal).ffill(limit=5)
    px = px.where(px > 0)
    dv = (close * vol).reindex(cal).rolling(60, min_periods=40).mean()
    liquid = (px[tick] >= MIN_PRICE) & (dv[tick] >= MIN_DOLLAR_VOL)
    liquid = liquid.fillna(False)

    buckets = {b: g["ticker"].tolist() for b, g in u.groupby("bucket")}
    ind_groups = {f"{s}|{i}": g["ticker"].tolist() for (s, i), g in u.groupby(["sector", "industry"]) if len(g) >= 5}
    per_stock = {t: [t] for t in tick}
    # "physical" chain = the parts AI bottlenecks have historically formed in (chips, gear, power, build-out).
    # Software / generic IT services / generic industrial machinery left out.
    PHYS = {"semis", "tech_equipment", "hardware", "networking", "electrical", "power", "construction"}
    phys_buckets = {b: v for b, v in buckets.items() if b in PHYS}
    phys_stock = {t: [t] for b in phys_buckets.values() for t in b}
    liquid_big = ((px[tick] >= MIN_PRICE) & (dv[tick] >= 100e6)).fillna(False)

    top6 = {"portfolio": {"layers_to_hold": 6, "stocks_per_layer": 1, "keep_if_rank_at_most": 15, "max_weight": 0.30}}
    variants = {
        "E: שרשרת פיזית, 3 ענפים x 2": (make_uni(phys_buckets, BUCKET_HE), {}),
        "F: שרשרת פיזית, 6 החזקות": (make_uni(phys_stock, {}), top6),
        "G: שרשרת פיזית, 3x2, רק מניות עם 100M$ ביום": (make_uni(phys_buckets, BUCKET_HE), {}, liquid_big),
        "H: שרשרת פיזית, 6 החזקות, 100M$ ביום": (make_uni(phys_stock, {}), top6, liquid_big),
        "A: 10 ענפים, 3 ענפים x 2 מניות (החוקים הנוכחיים)": (make_uni(buckets, BUCKET_HE), {}),
        "B: תעשיות מפורטות, 3 x 2": (make_uni(ind_groups, {}), {}),
        "C: 6 המניות החזקות ביותר": (make_uni(per_stock, {}),
                                     {"portfolio": {"layers_to_hold": 6, "stocks_per_layer": 1, "keep_if_rank_at_most": 15,
                                                    "max_weight": 0.30}}),
        "D: 10 המניות החזקות ביותר": (make_uni(per_stock, {}),
                                      {"portfolio": {"layers_to_hold": 10, "stocks_per_layer": 1, "keep_if_rank_at_most": 25,
                                                     "max_weight": 0.30}}),
    }
    starts = {"5y": "2021-11-12", "7y": "2019-01-02"}
    results, yearly, picks_now, navs5 = {}, {}, {}, {}
    trades_out = []
    for name, spec in variants.items():
        uni, ov = spec[0], spec[1]
        liq = spec[2] if len(spec) > 2 else liquid
        r = merge_rules(rules, ov)
        for sk, s in starts.items():
            sim = run_variant(px, liq, uni, r, s)
            nav = sim["nav"]["nav"]
            st = perf_stats(nav)
            st["trades"] = len(sim["trades"])
            results.setdefault(name, {})[sk] = st
            if sk == "5y":
                navs5[name] = nav
                yearly[name] = yearly_returns(nav)
                t = sim["trades"].copy()
                t["variant"] = name
                trades_out.append(t)
                picks_now[name] = {"positions": [{"ticker": p["ticker"], "group": p["layer"], "weight": round(p["weight"], 3),
                                                  "pnl": round(p["pnl"], 3)} for p in sim["positions"]],
                                   "next_plan": (sorted(sim["pending_rebalance"]["targets"].items(), key=lambda x: -x[1])
                                                 if sim["pending_rebalance"] else None)}
        print(name, {k: round(v["cagr"], 3) for k, v in results[name].items()}, flush=True)

    for b in BENCH:
        for sk, s in starts.items():
            seg = px[b].loc[s:].dropna()
            results.setdefault(f"קנה והחזק {b}", {})[sk] = perf_stats(seg / seg.iloc[0])
        seg = px[b].loc[starts["5y"]:].dropna()
        navs5[f"קנה והחזק {b}"] = seg / seg.iloc[0]
        yearly[f"קנה והחזק {b}"] = yearly_returns(seg / seg.iloc[0])

    # momentum radar today: liquid chain stocks ranked by the live score
    ind = engine.indicators(px[tick])
    d = px.index[-1]
    live = [t for t in tick if liquid.at[d, t]]
    score = engine.composite_score(ind, d, live).sort_values(ascending=False)
    above = (px.loc[d, live] > ind["ma200"].loc[d, live])
    meta = u.set_index("ticker")
    radar = [{"ticker": t, "name": meta.at[t, "name"][:40], "bucket": meta.at[t, "bucket"],
              "industry": meta.at[t, "industry"], "score": round(float(s), 3),
              "r3m": round(float(ind["r3m"].at[d, t]), 3), "r6m": round(float(ind["r6m"].at[d, t]), 3),
              "above_ma200": bool(above[t]), "mcap_b": round(meta.at[t, "market_cap_now"] / 1e9, 1)}
             for t, s in score.head(40).items()]
    # when did today's leaders first become buyable (liquid)?  shows how early the filter lets them in
    first_liquid = {t: str(liquid[t].idxmax().date()) if liquid[t].any() else None for t in tick}

    pd.DataFrame(navs5).to_csv(OUT / "broad_nav_5y.csv", float_format="%.5f", index_label="date")
    pd.DataFrame(yearly).to_csv(OUT / "broad_yearly.csv", float_format="%.4f", index_label="year")
    pd.concat(trades_out).to_csv(OUT / "broad_trades_5y.csv", index=False, float_format="%.4f")
    (OUT / "broad_summary.json").write_text(json.dumps({
        "asof": str(d.date()), "universe_size": len(tick), "liquid_today": len(live),
        "rules": {"min_price": MIN_PRICE, "min_dollar_vol": MIN_DOLLAR_VOL},
        "results": results, "picks_now": picks_now, "radar": radar,
        "first_liquid": {t: first_liquid[t] for t in [r["ticker"] for r in radar]},
    }, indent=1, ensure_ascii=False, default=str), encoding="utf-8")

    pd.set_option("display.width", 220)
    tbl = pd.DataFrame({k: {f"{sk}_{m}": v[sk][m] for sk in v for m in ("cagr", "max_drawdown", "sharpe")}
                        for k, v in results.items()}).T
    print(tbl.round(3))
    print((pd.DataFrame(yearly) * 100).round(1))


if __name__ == "__main__":
    main()
