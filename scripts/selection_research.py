"""Two honesty checks on the switch, and the two ideas Roey asked about.

A. Survivorship. The 380-name list is TODAY's listings, so a stock that was delisted
   since 2018 (bankrupt or bought) can never appear in the backtest. Three checks:
     PIT       point-in-time list: semi-annual snapshots of the US listing files from the
               history of github.com/rreichel3/US-Stock-Symbols. A stock is tradable on a day
               only if the latest snapshot before that day listed it in a physical-chain
               industry. Names that vanished since are added back where Yahoo still has
               their prices (most delisted names are gone from Yahoo; the count is reported).
     DROP_TOP  the 10 stocks that made the rotation the most money are removed.
     BOOT      20 runs, each with a random 20% of the list removed.
B. Selection. Fixed before the run, nothing tuned:
     N3 ... N15  hold 3, 4, 6 (today), 8, 10 or 15 stocks instead of 6
     DIP         6 stocks furthest below their 52-week high, among those still up over
                 12-1 months (buy the dip inside an uptrend). No MA200 entry or exit.
     DEEP        6 stocks furthest below their 52-week high, no trend condition at all.
   Judged the same way as before: calibration 2018-22, unseen 2023-26. A variant replaces
   the current rule only if its switch beats the current switch by >= 3 points a year in
   BOTH periods and its worst fall is not more than 5 points deeper. Plus a walk-forward
   over N: each January take the N with the best 3-year Sharpe so far, hold it a year.

Every variant runs through build_switch, the same code as the live system.
Usage (GitHub Actions): python scripts/selection_research.py
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

import engine
from broad_research import BUCKETS, MIN_PRICE, download
from bottleneck_research import IS_END, IS_START, OOS_START, OUT, PHYS, RAW
from systematic_rules import build_switch, load_prices

REPO = "https://github.com/rreichel3/US-Stock-Symbols"
SEEDS = int(__import__("os").environ.get("SEL_SEEDS", 20))
DV_MIN = 100e6


# ------------------------------------------------------------------ point-in-time listings
def listing_snapshots() -> dict[pd.Timestamp, pd.DataFrame]:
    tmp = Path(tempfile.mkdtemp())
    subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", REPO, str(tmp)], check=True)
    log = subprocess.run(["git", "-C", str(tmp), "log", "--format=%H %cs", "--", "nasdaq/nasdaq_full_tickers.json"],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    commits = sorted((pd.Timestamp(l.split()[1]), l.split()[0]) for l in log if l.strip())
    print("listing history:", commits[0][0].date(), "->", commits[-1][0].date(), len(commits), "commits", flush=True)
    wanted, snaps = [], {}
    for y in range(commits[0][0].year, commits[-1][0].year + 1):
        for m in (1, 7):
            t = pd.Timestamp(y, m, 1)
            before = [c for c in commits if c[0] <= t]
            if before:
                wanted.append(before[-1])
    wanted = sorted(set(wanted + [commits[0]]))
    for day, sha in wanted:
        rows = []
        for ex in ("nasdaq", "nyse", "amex"):
            r = subprocess.run(["git", "-C", str(tmp), "show", f"{sha}:{ex}/{ex}_full_tickers.json"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                continue
            try:
                data = json.loads(r.stdout)
            except json.JSONDecodeError:
                continue
            for x in data:
                sym = str(x.get("symbol", "")).strip()
                if not sym or "^" in sym or "/" in sym or " " in sym:
                    continue
                try:
                    mc = float(x.get("marketCap") or 0)
                except (TypeError, ValueError):
                    mc = 0.0
                rows.append({"ticker": sym.replace(".", "-"), "sector": x.get("sector") or "",
                             "industry": x.get("industry") or "", "mc": mc})
        if rows:
            snaps[day] = pd.DataFrame(rows).drop_duplicates("ticker")
            print("snapshot", day.date(), len(rows), "listings", flush=True)
    return snaps


def chain_members(df: pd.DataFrame, fallback: dict[str, str]) -> set[str]:
    out = set()
    for t, s, i, mc in df[["ticker", "sector", "industry", "mc"]].itertuples(index=False):
        b = BUCKETS.get((s, i)) or BUCKETS.get(("*", i)) or (fallback.get(t) if not i else None)
        if b in PHYS and (mc >= 50e6 or not mc):
            out.add(t)
    return out


# ------------------------------------------------------------------ stats
def stats(nav: pd.Series, a=None, b=None) -> dict:
    s = nav.loc[a:b].dropna()
    s = s / s.iloc[0]
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    r = s.pct_change().dropna()
    return {"cagr": round(float(s.iloc[-1] ** (1 / yrs) - 1), 4),
            "max_dd": round(float((s / s.cummax() - 1).min()), 4),
            "sharpe": round(float(r.mean() / r.std() * np.sqrt(252)), 2) if r.std() > 0 else None}


def periods(nav: pd.Series) -> dict:
    end = nav.index[-1]
    five = nav.index[nav.index <= end - pd.DateOffset(years=5)][-1]
    return {"full_2018_2026": stats(nav, IS_START), "calibration_2018_2022": stats(nav, IS_START, IS_END),
            "unseen_2023_2026": stats(nav, OOS_START), "last_5y": stats(nav, five)}


def yearly(nav: pd.Series) -> pd.Series:
    y = nav.resample("YE").last()
    first = nav.iloc[0]
    return pd.concat([pd.Series([first], index=[nav.index[0]]), y]).pct_change().dropna().set_axis(y.index.year)


def run(px, mask, tick, override=None) -> dict:
    S = build_switch(px, mask, tick, override=override)
    return {"switch": S["switch_trend"], "rotation": S["h_park"], "smh": S["smh"], "sim": S["sim"]}


# ------------------------------------------------------------------ main
def main() -> None:
    px, dv, tick = load_prices()
    liquid = ((px[tick] >= MIN_PRICE) & (dv[tick] >= DV_MIN)).fillna(False)
    res, navs = {}, {}

    base = run(px, liquid, tick)
    navs["SMH"], navs["CURRENT"] = base["smh"], base["switch"]
    res["SMH"] = periods(base["smh"])
    res["CURRENT"] = periods(base["switch"])
    print("CURRENT", res["CURRENT"], flush=True)

    # ---------------- A1. point-in-time listings
    u = pd.read_csv(OUT / "broad_universe.csv")
    fallback = dict(zip(u["ticker"], u["bucket"]))
    pit_info = {}
    try:
        snaps = listing_snapshots()
        members = {d: chain_members(df, fallback) for d, df in snaps.items()}
        ever = set().union(*members.values())
        gone = sorted(ever - set(u["ticker"]) - set(px.columns))
        print(f"names listed in the chain at some point but not today: {len(gone)}", flush=True)
        got = []
        if gone:
            c2, v2 = download(gone)
            c2 = c2.loc[:, c2.notna().sum() > 60]
            got = [t for t in c2.columns if t in gone]
            if got:
                cal = px.index
                c2 = c2[got].reindex(cal).ffill(limit=5)
                c2 = c2.where(c2 > 0)
                d2 = (c2 * v2[got].reindex(cal)).rolling(60, min_periods=40).mean()
                px = pd.concat([px, c2], axis=1)
                dv = pd.concat([dv, d2], axis=1)
        tick_pit = [t for t in dict.fromkeys(tick + got) if t in px.columns]
        days = sorted(members)
        snap_of = pd.Series([max([s for s in days if s <= d], default=days[0]) for d in px.index], index=px.index)
        mem = pd.DataFrame(False, index=px.index, columns=tick_pit)
        for s in days:
            rows = snap_of == s
            cols = [t for t in tick_pit if t in members[s]]
            mem.loc[rows, cols] = True
        liq_pit = ((px[tick_pit] >= MIN_PRICE) & (dv[tick_pit] >= DV_MIN)).fillna(False) & mem
        pit = run(px, liq_pit, tick_pit)
        navs["PIT"] = pit["switch"]
        res["PIT"] = periods(pit["switch"])
        ever_liquid_gone = [t for t in got if bool(((px[t] >= MIN_PRICE) & (dv[t] >= DV_MIN)).any())]
        held_gone = sorted(set(pit["sim"]["trades"]["ticker"]) & set(got)) if len(pit["sim"]["trades"]) else []
        pit_info = {"first_snapshot": str(days[0].date()), "snapshots": len(days),
                    "vanished_chain_names": len(gone), "vanished_with_prices": len(got),
                    "vanished_ever_100m_liquid": ever_liquid_gone, "vanished_bought_by_rotation": held_gone,
                    "current_names_not_listed_in_chain_at_first_snapshot":
                        len(set(tick) - members[days[0]])}
        print("PIT", res["PIT"], pit_info, flush=True)
    except Exception as e:  # keep the other checks if the listing history is unreachable
        pit_info = {"error": str(e)[:300]}
        print("PIT failed:", e, flush=True)


    # ---------------- A2. drop the 10 biggest winners
    tr = base["sim"]["trades"]
    pnl = (-tr.groupby("ticker")["value"].sum()).to_dict()
    for p in base["sim"]["positions"]:
        pnl[p["ticker"]] = pnl.get(p["ticker"], 0.0) + p["weight"] * float(base["sim"]["nav"]["nav"].iloc[-1])
    top10 = [t for t, _ in sorted(pnl.items(), key=lambda x: -x[1])[:10]]
    keep = [t for t in tick if t not in top10]
    dt = run(px, liquid[keep], keep)
    navs["DROP_TOP10"] = dt["switch"]
    res["DROP_TOP10"] = periods(dt["switch"])
    res["DROP_TOP10"]["dropped"] = top10
    print("DROP_TOP10", res["DROP_TOP10"], flush=True)

    # ---------------- A3. random 20% removed
    boot = []
    for seed in range(SEEDS):
        rng = np.random.default_rng(seed)
        keep = sorted(rng.choice(tick, size=int(len(tick) * 0.8), replace=False).tolist())
        b = run(px, liquid[keep], keep)
        boot.append({k: v["cagr"] for k, v in periods(b["switch"]).items()})
        print("boot", seed, boot[-1], flush=True)
    bdf = pd.DataFrame(boot)
    res["BOOT_80PCT"] = {k: {"median": round(float(bdf[k].median()), 4), "p10": round(float(bdf[k].quantile(.1)), 4),
                             "p90": round(float(bdf[k].quantile(.9)), 4), "min": round(float(bdf[k].min()), 4)}
                         for k in bdf.columns}

    # ---------------- B. selection variants
    def ov(n):
        return {"portfolio": {"layers_to_hold": n, "keep_if_rank_at_most": max(5, int(round(2.5 * n))),
                              "max_weight": max(0.30, round(1.0 / n + 0.01, 3))}}

    for n in (3, 4, 6, 8, 10, 15):
        k = f"N{n}"
        v = base if n == 6 else run(px, liquid, tick, ov(n))
        navs[k] = v["switch"]
        res[k] = periods(v["switch"])
        res[k]["rotation_alone"] = periods(v["rotation"])
        print(k, res[k]["full_2018_2026"], res[k]["unseen_2023_2026"], flush=True)

    orig = engine.composite_score

    def dip_score(trend: bool):
        def cs(ind, d, names):
            names = list(names)
            if not names:
                return pd.Series(dtype=float)
            dd = ind["dd52"].loc[d, names].astype(float)
            if trend:
                dd = dd.where(ind["r12_1"].loc[d, names] > 0)
            return (-dd).rank(pct=True)
        return cs

    mr = {"portfolio": {"entry_above_ma200": False}, "exits": {"trend_exit": False}}
    for k, trend in (("DIP", True), ("DEEP", False)):
        engine.composite_score = dip_score(trend)
        try:
            v = run(px, liquid, tick, mr)
        finally:
            engine.composite_score = orig
        navs[k] = v["switch"]
        res[k] = periods(v["switch"])
        res[k]["rotation_alone"] = periods(v["rotation"])
        print(k, res[k]["full_2018_2026"], res[k]["unseen_2023_2026"], flush=True)

    # ---------------- walk-forward over N
    rets = {k: navs[k].pct_change().fillna(0.0) for k in ("N3", "N4", "N6", "N8", "N10", "N15")}
    idx = navs["N6"].index
    wf, picks = [], {}
    for y in sorted(set(idx.year)):
        if y < 2021:
            continue
        past = slice(pd.Timestamp(y - 3, 1, 1), pd.Timestamp(y - 1, 12, 31))
        sh = {k: float(r.loc[past].mean() / r.loc[past].std()) for k, r in rets.items()}
        best = max(sh, key=sh.get)
        picks[y] = best
        wf.append(rets[best].loc[str(y)])
    wf_nav = (1 + pd.concat(wf)).cumprod()
    navs["WF_N"] = wf_nav
    start = wf_nav.index[0]
    res["WF_N"] = {"picks": picks, "since_2021": stats(wf_nav),
                   "current_since_2021": stats(navs["CURRENT"], start), "smh_since_2021": stats(navs["SMH"], start)}

    # ---------------- verdict (pre-registered)
    cur = res["CURRENT"]
    verdict = {}
    for k in ("N3", "N4", "N8", "N10", "N15", "DIP", "DEEP"):
        c, o = res[k]["calibration_2018_2022"], res[k]["unseen_2023_2026"]
        add_c = c["cagr"] - cur["calibration_2018_2022"]["cagr"]
        add_o = o["cagr"] - cur["unseen_2023_2026"]["cagr"]
        dd = res[k]["full_2018_2026"]["max_dd"] - cur["full_2018_2026"]["max_dd"]
        verdict[k] = {"calibration_add": round(add_c, 4), "unseen_add": round(add_o, 4), "max_dd_change": round(dd, 4),
                      "replace_current": bool(add_c >= 0.03 and add_o >= 0.03 and dd >= -0.05)}

    ydf = pd.DataFrame({k: yearly(v) for k, v in navs.items() if k != "WF_N"}).round(4)
    ydf.to_csv(OUT / "selection_yearly.csv", index_label="year")
    (OUT / "selection_summary.json").write_text(json.dumps(
        {"results": res, "point_in_time": pit_info, "verdict": verdict,
         "score_definition": "mean percentile rank of 3m, 6m and 12-1m return; must be above own MA200"},
        indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(verdict, indent=1))
    print(ydf)


if __name__ == "__main__":
    main()
