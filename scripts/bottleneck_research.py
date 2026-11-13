"""Does a *measurable* bottleneck signal add anything on top of momentum?

A company that is the bottleneck of the AI chain should show it in its own filings
before (or while) the market notices:
  - gross margin up vs a year ago          (pricing power)
  - revenue growth accelerating            (demand it can't fully meet)
  - inventory days down vs a year ago      (everything ships, nothing piles up)
  - customer prepayments up vs a year ago  (customers pay upfront to secure supply)
  - order backlog (RPO) up vs a year ago

Every number comes from SEC filings (XBRL company facts) and is used only from the
day AFTER the filing date, using the FIRST value ever filed for a quarter (later
restatements ignored). No look-ahead.

Tests (pre-registered, nothing tuned):
  1. Signal test: monthly cross-section of liquid physical-chain stocks. Does the
     score predict next-3-month returns? Does it add *inside* the momentum winners?
     Calibration period 2018-2022, out-of-sample 2023-2026, reported separately.
  2. Portfolio test on version H (physical chain, 6 holdings, $100M/day):
     baseline vs entry filter vs exit signal vs momentum+bottleneck blend.
  Kill rule: keep only if, out-of-sample, it adds >= 3 CAGR points or cuts max
  drawdown by >= 3 points without losing return; AND it also helps in 2018-2022;
  AND it beats 20 placebo runs (same filter, scores shuffled at random);
  AND the stock-level signal holds (out-of-sample t >= 1.5, same sign in 2018-2022).

Usage (GitHub Actions, needs sec.gov + Yahoo):  python scripts/bottleneck_research.py
Re-run on cached data:                          python scripts/bottleneck_research.py --offline
"""
from __future__ import annotations

import json
import pickle
import sys
import time
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

import engine
from broad_research import BENCH, MIN_DOLLAR_VOL, MIN_PRICE, download, make_uni
from engine import DATA, load_config, merge_rules, perf_stats, prepare, simulate, yearly_returns

OUT = DATA / "research"
RAW = DATA / "broad"
SEC_CACHE = RAW / "sec_facts.pkl"
UA = {"User-Agent": "ai-tracker-research research@example.com", "Accept-Encoding": "identity"}
PHYS = {"semis", "tech_equipment", "hardware", "networking", "electrical", "power", "construction"}

IS_START, IS_END, OOS_START = "2018-01-02", "2022-12-30", "2023-01-03"

REV = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
       "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"]
COGS = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
        "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"]
GP = ["GrossProfit"]
INV = ["InventoryNet", "InventoryGross"]
CL = ["ContractWithCustomerLiabilityCurrent", "ContractWithCustomerLiability", "CustomerAdvancesCurrent",
      "DeferredRevenueCurrent", "CustomerDepositsCurrent"]
RPO = ["RevenueRemainingPerformanceObligation"]
FLOW = {"rev": REV, "cogs": COGS, "gp": GP}
STOCK = {"inv": INV, "cl": CL, "rpo": RPO}

# feature -> direction (+1: higher = tighter supply)
FEATURES = {"gm_chg": 1, "rev_yoy": 1, "rev_accel": 1, "dio_chg": -1, "cl_g": 1, "rpo_g": 1}


# ---------------------------------------------------------------- SEC download
def _get(url: str):
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def _extract(facts: dict) -> dict:
    """Keep only the concepts we use, as compact lists."""
    gaap = (facts or {}).get("facts", {}).get("us-gaap", {})
    out = {}
    for c in REV + COGS + GP + INV + CL + RPO:
        if c in gaap:
            rows = gaap[c].get("units", {}).get("USD", [])
            out[c] = [(r.get("start"), r["end"], float(r["val"]), r["filed"], r.get("form", ""))
                      for r in rows if r.get("form", "").startswith(("10-Q", "10-K"))]
    return out


def fetch_sec(tickers: list[str]) -> dict:
    cache = pickle.loads(SEC_CACHE.read_bytes()) if SEC_CACHE.exists() else {}
    m = _get("https://www.sec.gov/files/company_tickers.json") or {}
    cik = {str(v["ticker"]).upper().replace(".", "-"): int(v["cik_str"]) for v in m.values()}
    print(f"SEC ticker map: {len(cik)}", flush=True)
    for i, t in enumerate(tickers):
        if t in cache or t.upper() not in cik:
            continue
        j = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik[t.upper()]:010d}.json")
        cache[t] = _extract(j) if j else {}
        time.sleep(0.15)
        if i % 50 == 0:
            print(f"sec {i}/{len(tickers)}", flush=True)
            SEC_CACHE.write_bytes(pickle.dumps(cache))
    SEC_CACHE.write_bytes(pickle.dumps(cache))
    return cache


# ---------------------------------------------------------------- quarterly series (point-in-time)
def _first_filed(rows):
    """One value per (start, end): the first one ever filed."""
    df = pd.DataFrame(rows, columns=["start", "end", "val", "filed", "form"])
    if df.empty:
        return df
    df["end"] = pd.to_datetime(df["end"])
    df["start"] = pd.to_datetime(df["start"])
    df["filed"] = pd.to_datetime(df["filed"])
    df = df.sort_values("filed").drop_duplicates(["start", "end"], keep="first")
    return df


def _key(end: pd.Series) -> pd.Series:
    """Nearest month (52/53-week years end a few days either side of a month end)."""
    return (end + pd.Timedelta(days=15)).dt.to_period("M")


def _flow_quarters(facts: dict, concepts: list[str]) -> pd.DataFrame:
    """Quarterly (3-month) values; Q4 = fiscal year minus the three quarters inside it."""
    frames = []
    for pri, c in enumerate(concepts):
        df = _first_filed(facts.get(c, []))
        if df.empty or df["start"].isna().all():
            continue
        df = df.dropna(subset=["start"])
        days = (df["end"] - df["start"]).dt.days
        q = df[(days >= 80) & (days <= 100)][["end", "val", "filed"]]
        y = df[(days >= 350) & (days <= 380)]
        q4 = []
        for _, r in y.iterrows():
            inside = q[(q["end"] > r["start"] + pd.Timedelta(days=60)) & (q["end"] < r["end"] - pd.Timedelta(days=60))]
            if len(inside) == 3 and not ((q["end"] - r["end"]).abs() <= pd.Timedelta(days=10)).any():
                q4.append({"end": r["end"], "val": r["val"] - inside["val"].sum(), "filed": r["filed"]})
        q = pd.concat([q, pd.DataFrame(q4)], ignore_index=True) if q4 else q
        q = q.assign(pri=pri)
        frames.append(q)
    if not frames:
        return pd.DataFrame(columns=["end", "val", "filed"])
    allq = pd.concat(frames)
    allq["key"] = _key(allq["end"])
    allq = allq.sort_values(["key", "pri", "filed"])
    return allq.drop_duplicates("key", keep="first")[["end", "val", "filed", "key"]]


def _stock_values(facts: dict, concepts: list[str]) -> pd.DataFrame:
    frames = []
    for pri, c in enumerate(concepts):
        df = _first_filed(facts.get(c, []))
        if df.empty:
            continue
        frames.append(df[["end", "val", "filed"]].assign(pri=pri))
    if not frames:
        return pd.DataFrame(columns=["end", "val", "filed", "key"])
    s = pd.concat(frames)
    s["key"] = _key(s["end"])
    s = s.sort_values(["key", "pri", "filed"])
    return s.drop_duplicates("key", keep="first")


def company_features(t: str, facts: dict) -> pd.DataFrame:
    rev = _flow_quarters(facts, REV)
    if len(rev) < 6:
        return pd.DataFrame()
    df = rev.rename(columns={"val": "rev", "filed": "avail"}).set_index("key")
    for name, concepts in (("cogs", COGS), ("gp", GP)):
        f = _flow_quarters(facts, concepts)
        df[name] = f.set_index("key")["val"].reindex(df.index) if len(f) else np.nan
    for name, concepts in STOCK.items():
        s = _stock_values(facts, concepts)
        df[name] = s.set_index("key")["val"].reindex(df.index) if len(s) else np.nan
    df = df.sort_index()
    df = df[~df.index.duplicated()]
    full = df.reindex(pd.period_range(df.index.min(), df.index.max(), freq="M"))
    gp = full["gp"].where(full["gp"].notna(), full["rev"] - full["cogs"])
    cogs = full["cogs"].where(full["cogs"].notna(), full["rev"] - full["gp"])
    rev = full["rev"].where(full["rev"] > 0)
    gm = gp / rev
    lag = lambda s, n: s.shift(n)      # monthly index: 12 = one year, 3 = one quarter
    out = pd.DataFrame(index=full.index)
    out["end"] = full["end"]
    out["avail"] = full["avail"]
    out["gm"] = gm.where(gm.between(-1, 1))
    out["gm_chg"] = out["gm"] - lag(out["gm"], 12)
    out["rev_yoy"] = (rev / lag(rev, 12) - 1).clip(-0.9, 3)
    out["rev_accel"] = out["rev_yoy"] - lag(out["rev_yoy"], 3)
    dio = full["inv"] / cogs.where(cogs > 0) * 91
    out["dio_chg"] = (dio / lag(dio, 12) - 1).clip(-0.9, 3)
    out["cl_g"] = (full["cl"] / lag(full["cl"], 12).where(lag(full["cl"], 12) > 0) - 1).clip(-0.9, 3)
    out["rpo_g"] = (full["rpo"] / lag(full["rpo"], 12).where(lag(full["rpo"], 12) > 0) - 1).clip(-0.9, 3)
    out = out.dropna(subset=["end", "avail"])
    out["ticker"] = t
    return out.reset_index(drop=True)


# ---------------------------------------------------------------- score on any date
def score_table(feat: pd.DataFrame, dates: pd.DatetimeIndex, universe_at) -> dict[pd.Timestamp, pd.DataFrame]:
    """For each date d: each ticker's latest quarter filed BEFORE d (and not stale),
    cross-sectional percentile ranks, mean = bottleneck score (needs >= 3 features)."""
    feat = feat.sort_values("avail")
    out = {}
    for d in dates:
        names = universe_at(d)
        f = feat[(feat["avail"] < d) & (feat["end"] >= d - pd.Timedelta(days=200)) & feat["ticker"].isin(names)]
        f = f.drop_duplicates("ticker", keep="last").set_index("ticker")
        if f.empty:
            out[d] = pd.DataFrame()
            continue
        ranks = pd.DataFrame({k: (f[k] * s).rank(pct=True) for k, s in FEATURES.items()})
        n = ranks.notna().sum(axis=1)
        f["score"] = ranks.mean(axis=1).where(n >= 3)
        # pre-registered exit flag: margins down vs last year AND growth slowing
        f["easing"] = (f["gm_chg"] < 0) & (f["rev_accel"] < 0)
        out[d] = f
    return out


# ---------------------------------------------------------------- 1. signal test
def signal_test(px, liquid, mom_hist, scores, month_ends) -> dict:
    fwd = px.shift(-64) / px.shift(-1) - 1          # buy next close, hold ~3 months
    rows = []
    for d in month_ends:
        f = scores.get(d)
        if f is None or f.empty:
            continue
        live = [t for t in f.index if t in px.columns and liquid.at[d, t]]
        s = f.loc[live, "score"].dropna()
        r = fwd.loc[d, s.index].dropna()
        s = s.loc[r.index]
        if len(s) < 30:
            continue
        m = mom_hist.loc[d, s.index]
        above = px.loc[d, s.index] > px[s.index].rolling(200).mean().loc[d]
        top_mom = m >= m.quantile(0.8)
        q = pd.qcut(s.rank(method="first"), 5, labels=False)
        tm = s[top_mom]
        rows.append({
            "date": d,
            "n": len(s),
            "ic": float(s.rank().corr(r.rank())),
            "ic_mom": float(m.rank().corr(r.rank())),
            "q5_minus_q1": float(r[q == 4].mean() - r[q == 0].mean()),
            # inside the momentum winners: does high bottleneck score beat low?
            "in_mom_hi_minus_lo": float(r[tm.index][tm >= tm.median()].mean() - r[tm.index][tm < tm.median()].mean())
            if len(tm) >= 6 else np.nan,
            # among uptrending stocks
            "in_trend_hi_minus_lo": float(r[above & (s >= s.median())].mean() - r[above & (s < s.median())].mean()),
            "easing_minus_rest": float(r[f.loc[s.index, "easing"]].mean() - r[~f.loc[s.index, "easing"]].mean()),
        })
    df = pd.DataFrame(rows).set_index("date")

    def summ(x: pd.DataFrame) -> dict:
        res = {"months": len(x)}
        q = x.iloc[::3]                                  # non-overlapping (3-month) for the t-stat
        for c in ["ic", "ic_mom", "q5_minus_q1", "in_mom_hi_minus_lo", "in_trend_hi_minus_lo", "easing_minus_rest"]:
            v, vq = x[c].dropna(), q[c].dropna()
            res[c] = round(float(v.mean()), 4)
            res[c + "_t"] = round(float(vq.mean() / (vq.std() / np.sqrt(len(vq)))), 2) if len(vq) > 2 else None
            res[c + "_hit"] = round(float((v > 0).mean()), 2)
        return res

    return {"calibration_2018_2022": summ(df.loc[:IS_END]), "out_of_sample_2023_2026": summ(df.loc[OOS_START:]),
            "per_year_q5_minus_q1": df["q5_minus_q1"].groupby(df.index.year).mean().round(4).to_dict(),
            "per_year_in_mom": df["in_mom_hi_minus_lo"].groupby(df.index.year).mean().round(4).to_dict(),
            "per_year_easing": df["easing_minus_rest"].groupby(df.index.year).mean().round(4).to_dict()}, df


# ---------------------------------------------------------------- 2. portfolio test
def run(px, liquid, uni, rules, start, end, mode, scores, sorted_dates):
    """mode: base | filter | filter_strict | exit | filter_exit | blend | pure"""
    orig_pick, orig_cs = engine.pick_targets, engine.composite_score

    def at(d):
        i = sorted_dates.searchsorted(d, side="right") - 1
        return scores.get(sorted_dates[i]) if i >= 0 else None

    def pick(d, *a, exclude=None, **k):
        row = liquid.loc[d] if d in liquid.index else None
        bad = set(row.index[~row]) if row is not None else set()
        f = at(d)
        if f is not None and not f.empty and mode != "base":
            if mode in ("filter", "filter_exit"):
                bad |= set(f.index[f["score"] < 0.5])
            if mode == "filter_strict":
                ok = set(f.index[f["score"] >= 0.5])
                bad |= {t for t in px.columns if t not in ok}
            if mode in ("exit", "filter_exit"):
                bad |= set(f.index[f["easing"]])
        return orig_pick(d, *a, exclude=set(exclude or ()) | bad, **k)

    def cs(ind, d, names):
        mom = orig_cs(ind, d, names)
        if mode not in ("blend", "pure") or mom.empty:
            return mom
        f = at(d)
        b = f["score"].reindex(mom.index) if f is not None and not f.empty else pd.Series(np.nan, index=mom.index)
        b = b.fillna(0.5)                       # no filings = neutral, not excluded
        return b if mode == "pure" else 0.5 * mom + 0.5 * b

    engine.pick_targets, engine.composite_score = pick, cs
    try:
        cols = [c for c in px.columns if c in set(engine.all_tickers(uni))]
        sub = px[cols]
        sim = simulate(sub, uni, rules, start, end=end, prepared=prepare(sub, uni))
    finally:
        engine.pick_targets, engine.composite_score = orig_pick, orig_cs
    return sim


def main() -> None:
    offline = "--offline" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    u = pd.read_csv(OUT / "broad_universe.csv")
    u = u[u["bucket"].isin(PHYS)]
    if offline or (RAW / "close.pkl").exists():
        close, vol = pd.read_pickle(RAW / "close.pkl"), pd.read_pickle(RAW / "vol.pkl")
    else:
        close, vol = download(u["ticker"].tolist() + BENCH)
        close.to_pickle(RAW / "close.pkl")
        vol.to_pickle(RAW / "vol.pkl")
    tick = [t for t in u["ticker"] if t in close.columns and close[t].notna().sum() > 260]

    facts = pickle.loads(SEC_CACHE.read_bytes()) if offline else fetch_sec(tick)
    feat = pd.concat([company_features(t, facts.get(t) or {}) for t in tick], ignore_index=True)
    print(f"features: {feat['ticker'].nunique()} companies, {len(feat)} company-quarters", flush=True)

    cal = close["SPY"].dropna().index
    px = close.reindex(cal).ffill(limit=5)
    px = px.where(px > 0)
    dv = (close * vol).reindex(cal).rolling(60, min_periods=40).mean()
    liquid = ((px[tick] >= MIN_PRICE) & (dv[tick] >= MIN_DOLLAR_VOL)).fillna(False)
    liquid_big = ((px[tick] >= MIN_PRICE) & (dv[tick] >= 100e6)).fillna(False)

    s = pd.Series(cal, index=cal)
    month_ends = pd.DatetimeIndex(s.groupby(cal.to_period("M")).max().values)
    month_ends = month_ends[month_ends >= pd.Timestamp("2017-12-01")]
    with_last = month_ends.append(pd.DatetimeIndex([cal[-1]])).unique()
    scores = score_table(feat, with_last, lambda d: [t for t in tick if liquid.at[d, t]])

    # 1. signal test
    ind = engine.indicators(px[tick])
    mom_hist = engine.composite_history(ind, tick)
    sig, sig_df = signal_test(px[tick], liquid, mom_hist, scores, month_ends)
    print(json.dumps(sig, indent=1, default=str), flush=True)

    # 2. portfolio test on version H
    _, rules = load_config()
    uni = make_uni({t: [t] for t in tick}, {})
    r = merge_rules(rules, {"portfolio": {"layers_to_hold": 6, "stocks_per_layer": 1, "keep_if_rank_at_most": 15,
                                          "max_weight": 0.30}})
    modes = {"base": "H: מומנטום בלבד (בסיס)",
             "filter": "H + סינון כניסה: ציון צוואר בקבוק 0.5 ומעלה",
             "filter_strict": "H + סינון קשיח (בלי דוחות = לא נכנסים)",
             "exit": "H + אות יציאה: מרווח יורד וצמיחה מאטה",
             "filter_exit": "H + סינון כניסה + אות יציאה",
             "blend": "H + דירוג משולב 50% מומנטום 50% צוואר בקבוק",
             "pure": "צוואר בקבוק בלבד (6 החזקות, מעל ממוצע 200)"}
    periods = {"calibration_2018_2022": (IS_START, IS_END), "out_of_sample_2023_2026": (OOS_START, None),
               "full_2018_2026": (IS_START, None)}
    results, navs, yearly = {}, {}, {}
    for mode, label in modes.items():
        for pk, (a, b) in periods.items():
            sim = run(px, liquid_big, uni, r, a, b, mode, scores, with_last)
            nav = sim["nav"]["nav"]
            st = perf_stats(nav)
            st["trades"] = len(sim["trades"])
            results.setdefault(label, {})[pk] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in st.items()}
            if pk == "full_2018_2026":
                navs[label] = nav
                yearly[label] = yearly_returns(nav)
        print(label, {k: round(v["cagr"], 3) for k, v in results[label].items()}, flush=True)
    for pk, (a, b) in periods.items():
        seg = px["SMH"].loc[a:b].dropna()
        results.setdefault("קנה והחזק SMH", {})[pk] = {k: (round(v, 4) if isinstance(v, float) else v)
                                                       for k, v in perf_stats(seg / seg.iloc[0]).items()}
    seg = px["SMH"].loc[IS_START:].dropna()
    navs["קנה והחזק SMH"] = seg / seg.iloc[0]
    yearly["קנה והחזק SMH"] = yearly_returns(seg / seg.iloc[0])

    # placebo: the same entry filter with the scores shuffled at random -> how big is pure luck?
    placebo = {}
    for seed in range(20):
        rng = np.random.default_rng(seed)
        shuf = {}
        for d0, f0 in scores.items():
            g = f0.copy()
            if not g.empty:
                g["score"] = rng.permutation(g["score"].values)
            shuf[d0] = g
        for pk in ("calibration_2018_2022", "out_of_sample_2023_2026"):
            a, b = periods[pk]
            sim = run(px, liquid_big, uni, r, a, b, "filter", shuf, with_last)
            placebo.setdefault(pk, []).append(round(perf_stats(sim["nav"]["nav"])["cagr"], 4))
    print("placebo (random filter) CAGR:", placebo, flush=True)

    # kill rule (pre-registered): must add in BOTH periods, and beat the best random filter out-of-sample
    base = results[modes["base"]]
    verdict = {}
    for mode, label in modes.items():
        if mode == "base":
            continue
        o, c = results[label]["out_of_sample_2023_2026"], results[label]["calibration_2018_2022"]
        add = o["cagr"] - base["out_of_sample_2023_2026"]["cagr"]
        add_cal = c["cagr"] - base["calibration_2018_2022"]["cagr"]
        dd_chg = o["max_drawdown"] - base["out_of_sample_2023_2026"]["max_drawdown"]
        dd_better = dd_chg >= 0.03 and add > -0.01
        beats_luck = o["cagr"] > max(placebo["out_of_sample_2023_2026"])
        # the stock-level signal itself must hold up too (a lucky portfolio path is not enough)
        metric, sign = {"exit": ("easing_minus_rest", -1), "blend": ("ic", 1), "pure": ("ic", 1)}.get(
            mode, ("in_trend_hi_minus_lo", 1))
        if mode == "filter_exit":
            metric = "in_trend_hi_minus_lo"
        so, sc = sig["out_of_sample_2023_2026"], sig["calibration_2018_2022"]
        signal_ok = bool((so[metric + "_t"] or 0) * sign >= 1.5 and sc[metric] * sign > 0)
        verdict[label] = {"oos_cagr_add": round(add, 4), "cal_cagr_add": round(add_cal, 4),
                          "oos_dd_change": round(dd_chg, 4), "beats_all_placebos": bool(beats_luck),
                          "signal_metric": metric, "signal_ok": signal_ok,
                          "keep": bool((add >= 0.03 or dd_better) and add_cal > 0 and beats_luck and signal_ok)}

    # today's bottleneck board
    d = cal[-1]
    f = scores[d].copy()
    meta = u.set_index("ticker")
    f = f[f["score"].notna()].sort_values("score", ascending=False)
    board = []
    for t, row in f.head(30).iterrows():
        board.append({"ticker": t, "name": str(meta.at[t, "name"])[:40], "bucket": meta.at[t, "bucket"],
                      "score": round(float(row["score"]), 3), "quarter_end": str(row["end"].date()),
                      "filed": str(row["avail"].date()),
                      "gross_margin": round(float(row["gm"]), 3) if pd.notna(row["gm"]) else None,
                      "gm_change_yoy": round(float(row["gm_chg"]), 3) if pd.notna(row["gm_chg"]) else None,
                      "rev_yoy": round(float(row["rev_yoy"]), 3) if pd.notna(row["rev_yoy"]) else None,
                      "rev_accel": round(float(row["rev_accel"]), 3) if pd.notna(row["rev_accel"]) else None,
                      "inventory_days_chg": round(float(row["dio_chg"]), 3) if pd.notna(row["dio_chg"]) else None,
                      "prepayments_yoy": round(float(row["cl_g"]), 3) if pd.notna(row["cl_g"]) else None,
                      "backlog_yoy": round(float(row["rpo_g"]), 3) if pd.notna(row["rpo_g"]) else None,
                      "momentum": round(float(mom_hist.at[d, t]), 3) if pd.notna(mom_hist.at[d, t]) else None,
                      "above_ma200": bool(px.at[d, t] > ind["ma200"].at[d, t]),
                      "easing": bool(row["easing"])})
    # curated layers: median bottleneck score per layer (companies.yaml)
    uni_c, _ = load_config()
    layer_board = {}
    for key, ts in engine.layer_members(uni_c).items():
        v = f["score"].reindex([t for t in ts if t in f.index]).dropna()
        if len(v):
            layer_board[uni_c["layers"][key]["name"]] = {"median_score": round(float(v.median()), 3), "n": len(v),
                                                         "top": v.sort_values(ascending=False).head(3).round(3).to_dict()}

    feat.to_csv(OUT / "bottleneck_features.csv", index=False, float_format="%.4f")
    sig_df.to_csv(OUT / "bottleneck_signal_monthly.csv", float_format="%.4f", index_label="date")
    pd.DataFrame(navs).to_csv(OUT / "bottleneck_nav.csv", float_format="%.5f", index_label="date")
    pd.DataFrame(yearly).to_csv(OUT / "bottleneck_yearly.csv", float_format="%.4f", index_label="year")
    (OUT / "bottleneck_summary.json").write_text(json.dumps({
        "asof": str(d.date()), "companies_with_filings": int(feat["ticker"].nunique()), "universe": len(tick),
        "signal_test": sig, "portfolio": results, "placebo_cagr": placebo, "kill_rule": verdict,
        "board_now": board, "layers_now": dict(sorted(layer_board.items(), key=lambda x: -x[1]["median_score"])),
    }, indent=1, ensure_ascii=False, default=str), encoding="utf-8")

    pd.set_option("display.width", 220)
    tbl = pd.DataFrame({k: {f"{pk[:3]}_{m}": v[pk][m] for pk in v for m in ("cagr", "max_drawdown")}
                        for k, v in results.items()}).T
    print(tbl.round(3))
    print(json.dumps(verdict, indent=1, ensure_ascii=False))
    print((pd.DataFrame(yearly) * 100).round(1))


if __name__ == "__main__":
    main()
