"""Do Taiwan's monthly sales lead the US layers of the AI chain?

Taiwanese companies must publish last month's revenue by the 10th of each month.
Most of the AI hardware chain is there: TSMC, the server builders (Quanta, Wiwynn,
Wistron), networking/optics (Accton, LuxNet), power/cooling (Delta, Fortune Electric,
Asia Vital) and memory (Nanya, Winbond, Phison). That is 2-3 months ahead of US
quarterly filings - exactly what the SEC test lacked.

Signal per layer (fixed before the run): median over its Taiwan companies of
  accel = YoY growth of the last 3 months' revenue  minus  the same number 3 months earlier
At a month-end decision we only use months <= previous month (published by the 10th).

Tests, same discipline as bottleneck_research.py:
  1. Signal: does accel > 0 predict the layer beating SMH over the next 3 months?
  2. Portfolio on the live rotation (93-company list, data/prices.csv):
     base | filter (skip a layer whose accel < 0) | blend (50% momentum rank + 50% accel rank)
     + 20 placebos (accel shuffled between layers). Same kill rule.

Usage (GitHub Actions): python scripts/taiwan_lead.py
"""
from __future__ import annotations

import json
import time
import urllib.request

import numpy as np
import pandas as pd

import engine
from engine import DATA, load_config, load_prices, perf_stats, prepare, simulate

OUT = DATA / "research"
CACHE = DATA / "broad" / "taiwan_revenue.csv"
START_REV = "2014-01-01"
IS_START, IS_END, OOS_START = "2019-01-02", "2022-12-30", "2023-01-03"

TW = {   # Taiwan code -> layer of config/universe.yaml
    "2330": "foundry", "3711": "foundry", "2449": "foundry",
    "2408": "memory", "2344": "memory", "2337": "memory", "8299": "memory", "3260": "memory",
    "3661": "compute", "3443": "compute", "5274": "compute",
    "2382": "servers", "6669": "servers", "3231": "servers", "2356": "servers", "2317": "servers", "2059": "servers",
    "3706": "servers",
    "2345": "networking", "4979": "networking", "3081": "networking", "3363": "networking", "2383": "networking",
    "6274": "networking", "3450": "networking",
    "2308": "power_equipment", "1519": "power_equipment", "1513": "power_equipment", "1503": "power_equipment",
    "3017": "power_equipment", "3324": "power_equipment", "3653": "power_equipment",
}


def fetch() -> pd.DataFrame:
    rows = []
    for code in TW:
        url = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue"
               f"&data_id={code}&start_date={START_REV}")
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    j = json.load(r)
                data = j.get("data") or []
                for x in data:
                    rows.append({"code": code, "year": int(x["revenue_year"]), "month": int(x["revenue_month"]),
                                 "revenue": float(x["revenue"])})
                print(code, len(data), j.get("msg", ""), flush=True)
                break
            except Exception as e:
                print(code, "error", e, flush=True)
                time.sleep(5 * (attempt + 1))
        time.sleep(1.0)
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("no Taiwan revenue downloaded")
    return df.drop_duplicates(["code", "year", "month"])


def layer_signal(rev: pd.DataFrame) -> pd.DataFrame:
    """index = revenue month (period), columns = layer, value = median accel."""
    rev = rev.copy()
    rev["period"] = pd.PeriodIndex.from_fields(year=rev["year"], month=rev["month"], freq="M")
    wide = rev.pivot_table(index="period", columns="code", values="revenue")
    wide = wide.reindex(pd.period_range(wide.index.min(), wide.index.max(), freq="M"))
    r3 = wide.rolling(3, min_periods=3).sum()
    g = r3 / r3.shift(12) - 1
    accel = (g - g.shift(3)).clip(-2, 2)
    out = {}
    for layer in sorted(set(TW.values())):
        cols = [c for c, L in TW.items() if L == layer and c in accel.columns]
        out[layer] = accel[cols].median(axis=1, skipna=True)
    sig = pd.DataFrame(out)
    sig["_all"] = accel.median(axis=1, skipna=True)
    return sig


def signal_at(sig: pd.DataFrame, d: pd.Timestamp) -> pd.Series:
    """Known at month-end d: revenue months up to the previous month."""
    last = pd.Period(d, freq="M") - 1
    s = sig.loc[:last]
    return s.iloc[-1] if len(s) else pd.Series(dtype=float)


def signal_test(lidx, sig, month_ends, smh) -> tuple[dict, pd.DataFrame]:
    fwd = lidx.shift(-64) / lidx.shift(-1) - 1
    fwd_smh = smh.shift(-64) / smh.shift(-1) - 1
    rows = []
    for d in month_ends:
        s = signal_at(sig, d).drop("_all", errors="ignore").dropna()
        for layer, a in s.items():
            if layer not in fwd.columns or pd.isna(fwd.at[d, layer]) or pd.isna(fwd_smh.get(d)):
                continue
            rows.append({"date": d, "layer": layer, "accel": a, "excess": fwd.at[d, layer] - fwd_smh[d]})
    df = pd.DataFrame(rows)

    def summ(x):
        m = x.groupby("date").apply(lambda g: g.loc[g["accel"] > 0, "excess"].mean() - g.loc[g["accel"] <= 0, "excess"].mean())
        m = m.dropna()
        q = m.iloc[::3]
        ic = x.groupby("date").apply(lambda g: g["accel"].rank().corr(g["excess"].rank()) if len(g) >= 4 else np.nan).dropna()
        qi = ic.iloc[::3]
        return {"months": int(len(m)),
                "up_minus_down": round(float(m.mean()), 4),
                "up_minus_down_t": round(float(q.mean() / (q.std() / np.sqrt(len(q)))), 2) if len(q) > 2 else None,
                "up_minus_down_hit": round(float((m > 0).mean()), 2),
                "ic": round(float(ic.mean()), 4),
                "ic_t": round(float(qi.mean() / (qi.std() / np.sqrt(len(qi)))), 2) if len(qi) > 2 else None}

    per_layer = {}
    for layer, g in df.groupby("layer"):
        up, dn = g.loc[g["accel"] > 0, "excess"], g.loc[g["accel"] <= 0, "excess"]
        per_layer[layer] = {"up": round(float(up.mean()), 4), "down": round(float(dn.mean()), 4),
                            "months_up": int(len(up)), "months_down": int(len(dn))}
    return {"calibration_2018_2022": summ(df[df["date"] <= IS_END]),
            "out_of_sample_2023_2026": summ(df[df["date"] >= OOS_START]),
            "per_layer_3m_excess_vs_smh": per_layer}, df


def run(px, uni, rules, start, end, mode, sig, prepared):
    orig_pick, orig_cs = engine.pick_targets, engine.composite_score
    members = engine.layer_members(uni)
    layer_keys = set(members)

    def pick(d, *a, exclude=None, **k):
        bad = set(exclude or ())
        if mode == "filter":
            s = signal_at(sig, d)
            for layer, v in s.drop("_all", errors="ignore").items():
                if pd.notna(v) and v < 0:
                    bad |= set(members.get(layer, []))
        return orig_pick(d, *a, exclude=bad, **k)

    def cs(ind, d, names):
        mom = orig_cs(ind, d, names)
        if mode != "blend" or mom.empty or not set(mom.index) <= layer_keys:
            return mom
        s = signal_at(sig, d).drop("_all", errors="ignore").reindex(mom.index)
        b = s.rank(pct=True).fillna(0.5)
        return 0.5 * mom + 0.5 * b

    engine.pick_targets, engine.composite_score = pick, cs
    try:
        sim = simulate(px, uni, rules, start, end=end, prepared=prepared)
    finally:
        engine.pick_targets, engine.composite_score = orig_pick, orig_cs
    return sim


def main() -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    rev = pd.read_csv(CACHE, dtype={"code": str}) if CACHE.exists() else fetch()
    rev.to_csv(CACHE, index=False)
    sig = layer_signal(rev)
    print("revenue months:", sig.index.min(), "->", sig.index.max(), flush=True)

    uni, rules = load_config()
    px = load_prices(uni)
    prepared = prepare(px, uni)
    _, lidx, _ = prepared
    cal = px.index
    s = pd.Series(cal, index=cal)
    month_ends = pd.DatetimeIndex(s.groupby(cal.to_period("M")).max().values)
    month_ends = month_ends[month_ends >= pd.Timestamp("2018-01-01")]
    sig_res, sig_df = signal_test(lidx, sig, month_ends, px["SMH"])
    print(json.dumps(sig_res, indent=1), flush=True)

    periods = {"calibration_2019_2022": (IS_START, IS_END), "out_of_sample_2023_2026": (OOS_START, None),
               "full_2019_2026": (IS_START, None)}
    labels = {"base": "רוטציה חיה (בסיס)", "filter": "+ דילוג על שכבה שהמכירות בטאיוואן מאטות בה",
              "blend": "+ דירוג משולב: מומנטום ומכירות טאיוואן"}
    res = {}
    for mode, label in labels.items():
        for pk, (a, b) in periods.items():
            st = perf_stats(run(px, uni, rules, a, b, mode, sig, prepared)["nav"]["nav"])
            res.setdefault(label, {})[pk] = {k: round(float(v), 4) for k, v in st.items()}
        print(label, {k: v["cagr"] for k, v in res[label].items()}, flush=True)

    placebo = {}
    layer_cols = [c for c in sig.columns if c != "_all"]
    for seed in range(20):
        rng = np.random.default_rng(seed)
        sh = sig.copy()
        sh[layer_cols] = np.array([rng.permutation(row) for row in sig[layer_cols].values])
        for mode in ("filter", "blend"):
            for pk in ("calibration_2019_2022", "out_of_sample_2023_2026"):
                a, b = periods[pk]
                placebo.setdefault(mode, {}).setdefault(pk, []).append(
                    round(perf_stats(run(px, uni, rules, a, b, mode, sh, prepared)["nav"]["nav"])["cagr"], 4))
    print("placebo:", placebo, flush=True)

    base = res[labels["base"]]
    so, sc = sig_res["out_of_sample_2023_2026"], sig_res["calibration_2018_2022"]
    signal_ok = bool((so["up_minus_down_t"] or 0) >= 1.5 and sc["up_minus_down"] > 0)
    verdict = {}
    for mode in ("filter", "blend"):
        o, c = res[labels[mode]]["out_of_sample_2023_2026"], res[labels[mode]]["calibration_2019_2022"]
        add = o["cagr"] - base["out_of_sample_2023_2026"]["cagr"]
        add_cal = c["cagr"] - base["calibration_2019_2022"]["cagr"]
        dd = o["max_drawdown"] - base["out_of_sample_2023_2026"]["max_drawdown"]
        beats = o["cagr"] > max(placebo[mode]["out_of_sample_2023_2026"])
        verdict[labels[mode]] = {"oos_cagr_add": round(add, 4), "cal_cagr_add": round(add_cal, 4),
                                 "oos_dd_change": round(dd, 4), "beats_all_placebos": bool(beats),
                                 "signal_ok": signal_ok,
                                 "keep": bool((add >= 0.03 or (dd >= 0.03 and add > -0.01)) and add_cal > 0
                                              and beats and signal_ok)}
    now = signal_at(sig, cal[-1]).round(3).to_dict()
    last_month = str(sig.dropna(how="all").index.max())
    (OUT / "taiwan_summary.json").write_text(json.dumps({
        "revenue_through": last_month, "companies": TW, "signal_test": sig_res, "portfolio": res,
        "placebo_cagr": placebo, "kill_rule": verdict, "layer_accel_now": now,
    }, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    sig.to_csv(OUT / "taiwan_layer_signal.csv", float_format="%.4f", index_label="month")
    print(json.dumps(verdict, indent=1, ensure_ascii=False))
    print("accel now:", now)


if __name__ == "__main__":
    main()
