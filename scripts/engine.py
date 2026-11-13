"""Shared logic for the live run (compute.py) and the backtest (backtest.py).

Both call simulate(), so the paper portfolio follows exactly the rules that
were tested on history. Timing rule everywhere: a decision is made on a close,
and executed on the NEXT trading day's close (no peeking).
"""
from __future__ import annotations

import copy
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from pandas.tseries.offsets import BDay

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS_DATA = ROOT / "docs" / "data"
SCORE_KEYS = ("r3m", "r6m", "r12_1")


# ---------------------------------------------------------------- config
def load_config():
    """universe.yaml holds the layers; companies.yaml holds one card per company
    (layer, status, why). Membership is built from the cards."""
    uni = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text(encoding="utf-8"))
    rules = yaml.safe_load((ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))
    comp_path = ROOT / "config" / "companies.yaml"
    if comp_path.exists():
        comp = yaml.safe_load(comp_path.read_text(encoding="utf-8"))
        cards = {str(t): c for t, c in comp["companies"].items()}
        for layer in uni["layers"].values():
            layer["tickers"] = []
        for t, c in cards.items():
            uni["layers"][c["layer"]]["tickers"].append(t)
        uni["signal_only"] = [t for t, c in cards.items() if c.get("status") in ("watch", "signal")]
        uni["news_names"] = {t: c.get("name", t) for t, c in cards.items()}
        uni["companies"] = cards
        uni["discovery"] = comp.get("discovery", [])
    return uni, rules


def layer_members(uni) -> dict[str, list[str]]:
    return {k: [str(t) for t in v["tickers"]] for k, v in uni["layers"].items()}


def layer_names(uni) -> dict[str, str]:
    return {k: v.get("name", k) for k, v in uni["layers"].items()}


def active_layers(uni) -> list[str]:
    """Layers the rotation may buy. monitor_only layers are tracked and scored, not traded."""
    return [k for k, v in uni["layers"].items() if not v.get("monitor_only")]


def stock_tickers(uni, active_only: bool = False) -> list[str]:
    out: list[str] = []
    keep = set(active_layers(uni)) if active_only else None
    for layer, ts in layer_members(uni).items():
        if keep is None or layer in keep:
            out += ts
    return list(dict.fromkeys(out))


def all_tickers(uni) -> list[str]:
    return list(dict.fromkeys(stock_tickers(uni) + [str(t) for t in uni.get("benchmarks", [])]))


def is_tradable(uni, ticker: str) -> bool:
    return ticker not in {str(t) for t in uni.get("signal_only", [])}


def merge_rules(base: dict, override: dict | None) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge_rules(out[k], v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------- data
def load_prices(uni, path: Path | None = None) -> pd.DataFrame:
    """Adjusted closes on the US trading calendar. Foreign closes are carried
    forward onto US days (max 5 days, so dead tickers don't look alive)."""
    path = path or DATA / "prices.csv"
    raw = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    raw = raw.apply(pd.to_numeric, errors="coerce")
    cal = raw[uni.get("calendar", "SPY")].dropna().index
    full = raw.reindex(raw.index.union(cal)).ffill(limit=5)
    px = full.reindex(cal)
    return px.where(px > 0)


def daily_returns(px: pd.DataFrame) -> pd.DataFrame:
    return px / px.shift(1) - 1


def indicators(px: pd.DataFrame) -> dict[str, pd.DataFrame]:
    r = daily_returns(px)
    return {
        "ma50": px.rolling(50, min_periods=50).mean(),
        "ma200": px.rolling(200, min_periods=200).mean(),
        "r1w": px / px.shift(5) - 1,
        "r1m": px / px.shift(21) - 1,
        "r3m": px / px.shift(63) - 1,
        "r6m": px / px.shift(126) - 1,
        "r12m": px / px.shift(252) - 1,
        "r12_1": px.shift(21) / px.shift(252) - 1,   # 12 months, skipping the last one
        "vol": r.rolling(63, min_periods=40).std() * math.sqrt(252),
        "high52": px.rolling(252, min_periods=20).max(),
    }


def layer_indices(px: pd.DataFrame, uni) -> pd.DataFrame:
    """Equal-weight index per layer (100 on the layer's first day)."""
    r = daily_returns(px)
    cols = {}
    for key, tickers in layer_members(uni).items():
        t = [x for x in tickers if x in px.columns]
        if not t:
            continue
        has_px = px[t].notna().any(axis=1)
        if not has_px.any():
            continue
        start = has_px.idxmax()
        lr = r[t].mean(axis=1, skipna=True).fillna(0.0)
        idx = (1 + lr).cumprod()
        idx = idx / idx.loc[start] * 100
        idx[idx.index < start] = np.nan
        cols[key] = idx
    return pd.DataFrame(cols)


def prepare(px: pd.DataFrame, uni):
    ind = indicators(px)
    lidx = layer_indices(px, uni)
    lind = indicators(lidx)
    return ind, lidx, lind


# ---------------------------------------------------------------- scores
def composite_score(ind, d, names) -> pd.Series:
    """Mean percentile rank of the 3m, 6m and 12-1m returns. 1.0 = strongest."""
    names = list(names)
    if not names:
        return pd.Series(dtype=float)
    ranks = [ind[k].loc[d, names].astype(float).rank(pct=True) for k in SCORE_KEYS]
    return pd.concat(ranks, axis=1).mean(axis=1, skipna=True)


def composite_history(ind, names) -> pd.DataFrame:
    """Same score as composite_score, for every date at once."""
    names = list(names)
    ranks = [ind[k][names].rank(axis=1, pct=True) for k in SCORE_KEYS]
    num = sum(r.fillna(0.0) for r in ranks)
    den = sum(r.notna().astype(float) for r in ranks)
    return num / den.where(den > 0)


def regime_at(px, ind, d, uni, rules) -> dict:
    rg = rules["regime"]
    members = [t for t in stock_tickers(uni, active_only=True) if t in px.columns]
    p, m = px.loc[d, members], ind["ma200"].loc[d, members]
    ok = p.notna() & m.notna()
    breadth = float((p[ok] > m[ok]).mean()) if ok.any() else float("nan")
    b = rg["benchmark"]
    bp, bm = px.at[d, b], ind["ma200"].at[d, b]
    have = pd.notna(bp) and pd.notna(bm)
    bench_up = bool(bp > bm) if have else True
    if bench_up and breadth >= rg["breadth_green"]:
        status = "green"
    elif not bench_up and breadth < rg["breadth_red"]:
        status = "red"
    else:
        status = "yellow"
    exposure = float(rg["exposure"][status]) if rg.get("enabled", True) else 1.0
    return {
        "status": status,
        "breadth": breadth,
        "benchmark": b,
        "bench_above_ma200": bench_up,
        "bench_dist_ma200": float(bp / bm - 1) if have else None,
        "exposure": exposure,
    }


def inverse_vol_weights(vol: pd.Series, cap: float) -> pd.Series:
    """Calmer stocks get more weight. Weights sum to 1, none above cap
    (if there are too few names to respect the cap, the rest stays in cash)."""
    v = vol.astype(float)
    fill = float(v.median()) if v.notna().any() else 0.40
    v = v.fillna(fill).clip(lower=0.05)
    w = (1 / v) / (1 / v).sum()
    if len(w) * cap <= 1.0:
        return pd.Series(cap, index=w.index)
    for _ in range(50):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = float((w[over] - cap).sum())
        w[over] = cap
        free = w < cap - 1e-12
        if not free.any():
            break
        w[free] += excess * w[free] / w[free].sum()
    return w


def pick_targets(d, px, ind, lidx, lind, uni, rules, held=None, exclude=None) -> dict:
    """The monthly decision: which layers, which stocks, what weights."""
    held = held or {}
    exclude = exclude or set()
    P = rules["portfolio"]
    members = layer_members(uni)
    reg = regime_at(px, ind, d, uni, rules)

    layers = [L for L in active_layers(uni) if L in lidx.columns]
    score = composite_score(lind, d, layers)
    lp, lm = lidx.loc[d, layers], lind["ma200"].loc[d, layers]
    eligible = score.notna() & lp.notna() & lm.notna() & (lp > lm)
    rank = score.rank(ascending=False, method="min")
    order = score[eligible].sort_values(ascending=False).index.tolist()

    def stocks_for(layer: str) -> list[str]:
        ok = []
        for t in members[layer]:
            if t not in px.columns or not is_tradable(uni, t) or t in exclude:
                continue
            p, m = px.at[d, t], ind["ma200"].at[d, t]
            if pd.notna(p) and pd.notna(m) and p > m:
                ok.append(t)
        if not ok:
            return []
        sc = composite_score(ind, d, ok).dropna().sort_values(ascending=False)
        k = int(P["stocks_per_layer"])
        top = sc.index[:k].tolist()
        # a stock we already hold that is next in line keeps its seat (less churn)
        for t in sc.index[k:k + 1]:
            if held.get(t) == layer:
                unheld = [x for x in reversed(top) if held.get(x) != layer]
                if unheld:
                    top[top.index(unheld[0])] = t
        return top

    chosen: list[tuple[str, list[str]]] = []
    for layer in dict.fromkeys(held.values()):
        if layer in order and rank[layer] <= P["keep_if_rank_at_most"]:
            s = stocks_for(layer)
            if s:
                chosen.append((layer, s))
    for layer in order:
        if len(chosen) >= P["layers_to_hold"]:
            break
        if any(layer == c[0] for c in chosen):
            continue
        s = stocks_for(layer)
        if s:
            chosen.append((layer, s))
    chosen = sorted(chosen, key=lambda c: rank[c[0]])[: int(P["layers_to_hold"])]

    tickers = [t for _, ss in chosen for t in ss]
    layer_of = {t: L for L, ss in chosen for t in ss}
    vol = ind["vol"].loc[d, tickers] if tickers else pd.Series(dtype=float)
    # every chosen layer gets an equal slice; inside a layer the calmer stock gets more
    weights: dict[str, float] = {}
    cap = float(P["max_weight"])
    for _, ss in chosen:
        inner = inverse_vol_weights(vol[ss], 1.0)
        for t in ss:
            weights[t] = min(cap, float(inner[t]) / len(chosen))   # anything above the cap stays in cash
    return {
        "date": d,
        "regime": reg,
        "layer_scores": score,
        "layer_rank": rank,
        "eligible": eligible,
        "layers": [L for L, _ in chosen],
        "targets": {t: weights[t] * reg["exposure"] for t in tickers},
        "layer_of": layer_of,
        "vol": {t: (float(vol[t]) if pd.notna(vol[t]) else None) for t in tickers},
    }


STAGES_HE = {
    "heating": "מתחמם: הכסף מתחיל לזרום",
    "leading": "מוביל: צוואר הבקבוק של עכשיו",
    "fading": "מאבד תאוצה: זמן לשחרר",
    "cold": "קר: הכסף עזב",
    "neutral": "באמצע",
}


def layer_stage(rank_now, rank_1m, rank_3m, above_ma200, r1m) -> str:
    """Price-based bottleneck lifecycle: heating -> leading -> fading -> cold.
    The weekly report confirms (or rejects) it with real-world data."""
    if rank_now is None or pd.isna(rank_now) or above_ma200 is None:
        return "neutral"
    if not above_ma200 or rank_now >= 9:
        return "cold"
    slipping = pd.notna(rank_1m) and rank_now - rank_1m >= 2
    if rank_now <= 6 and (slipping or (pd.notna(r1m) and r1m < -0.05)):
        return "fading"
    if rank_now <= 6 and pd.notna(rank_3m) and rank_3m - rank_now >= 3:
        return "heating"
    if rank_now <= 3:
        return "leading"
    return "neutral"


# ---------------------------------------------------------------- simulation
def stop_pct(vol, X) -> float:
    if vol is None or not np.isfinite(vol):
        return float(X["stop_max"])
    return float(np.clip(X["stop_mult_monthly_vol"] * vol / math.sqrt(12), X["stop_min"], X["stop_max"]))


def _next_trading_day(all_dates, d):
    j = all_dates.get_loc(d)
    return all_dates[j + 1] if j + 1 < len(all_dates) else d + BDay(1)


def _is_decision_day(all_dates, d, freq: str = "monthly") -> bool:
    """Last close of the month (default), of the week, or every close."""
    if freq == "daily":
        return True
    n = _next_trading_day(all_dates, d)
    if freq == "weekly":
        return n.isocalendar()[:2] != d.isocalendar()[:2]
    return n.month != d.month


def simulate(px, uni, rules, start, end=None, prepared=None) -> dict:
    """Day-by-day paper portfolio. Rebalance decided on each month's last close,
    exits checked every close; everything executes at the next close."""
    ind, lidx, lind = prepared or prepare(px, uni)
    P, X, PT = rules["portfolio"], rules["exits"], rules["profit_take"]
    cost = float(rules["costs_per_side"])
    all_dates = px.index
    end_ts = pd.Timestamp(end) if end else all_dates[-1]
    dates = all_dates[(all_dates >= pd.Timestamp(start)) & (all_dates <= end_ts)]
    if len(dates) == 0:
        raise ValueError("no trading days in range")
    i0 = all_dates.get_loc(dates[0])
    if i0 == 0:
        raise ValueError("need at least one trading day before start")

    cash = 1.0
    pos: dict[str, dict] = {}
    trades, rebalances, nav_rows = [], [], []
    pending_rebal = pick_targets(all_dates[i0 - 1], px, ind, lidx, lind, uni, rules)
    pending_exits: dict[str, tuple[str, float, str]] = {}

    def price(t, d):
        p = px.at[d, t]
        return pos[t]["last_px"] if pd.isna(p) else float(p)

    def nav_at(d):
        return cash + sum(pos[t]["units"] * price(t, d) for t in pos)

    def book(d, t, units, p, reason, layer):
        nonlocal cash
        val = units * p
        cash -= val + abs(val) * cost
        trades.append({"date": d, "ticker": t, "layer": layer, "action": "buy" if units > 0 else "sell",
                       "price": p, "value": val, "reason": reason})

    for d in dates:
        # 1) execute what was decided at the previous close
        for t, (kind, frac, reason) in list(pending_exits.items()):
            if t not in pos:
                del pending_exits[t]
                continue
            p = px.at[d, t]
            if pd.isna(p):
                continue
            u = pos[t]["units"] * (1.0 if kind == "all" else frac)
            book(d, t, -u, float(p), reason, pos[t]["layer"])
            pos[t]["units"] -= u
            if kind == "frac":
                pos[t]["pt_done"] = True
            if kind == "all" or pos[t]["units"] <= 1e-12:
                del pos[t]
            del pending_exits[t]

        if pending_rebal is not None:
            plan = pending_rebal
            targets = plan["targets"]
            for t in list(pos):
                if t not in targets:
                    book(d, t, -pos[t]["units"], price(t, d), "rebalance_out", pos[t]["layer"])
                    del pos[t]
            nav = nav_at(d)
            budget = nav * (1 - cost)
            buys = []
            for t, w in targets.items():
                p = px.at[d, t]
                if pd.isna(p):
                    continue
                p = float(p)
                cur = pos[t]["units"] * p if t in pos else 0.0
                diff = w * budget - cur
                if t in pos and abs(diff) < P["rebalance_band"] * nav:
                    continue
                if diff < 0:
                    book(d, t, diff / p, p, "rebalance_trim", pos[t]["layer"])
                    pos[t]["units"] += diff / p
                else:
                    buys.append((t, diff, p))
            need = sum(b[1] for b in buys)
            scale = min(1.0, (cash / (1 + cost)) / need) if need > 0 else 1.0
            for t, diff, p in buys:
                u = diff * scale / p
                if u <= 0:
                    continue
                if t in pos:
                    book(d, t, u, p, "rebalance_add", pos[t]["layer"])
                    pos[t]["units"] += u
                    pos[t]["pt_done"] = False
                else:
                    layer = plan["layer_of"][t]
                    book(d, t, u, p, "rebalance_in", layer)
                    pos[t] = {"units": u, "layer": layer, "entry_date": d, "entry_px": p, "peak": p,
                              "last_px": p, "pt_done": False, "stop_pct": stop_pct(plan["vol"].get(t), X)}
            rebalances.append({"signal_date": plan["date"], "exec_date": d,
                               "regime": plan["regime"]["status"], "exposure": plan["regime"]["exposure"],
                               "layers": plan["layers"], "targets": plan["targets"]})
            pending_rebal = None

        # 2) mark to market
        for t, s in pos.items():
            p = px.at[d, t]
            if pd.notna(p):
                s["last_px"] = float(p)
                s["peak"] = max(s["peak"], float(p))
        nav = nav_at(d)
        nav_rows.append({"date": d, "nav": nav, "cash": cash, "invested": (nav - cash) / nav if nav else 0.0})

        # 3) decisions at this close, executed at the next close
        for t, s in pos.items():
            p = px.at[d, t]
            if pd.isna(p) or t in pending_exits:
                continue
            ma200, ma50, r1w = ind["ma200"].at[d, t], ind["ma50"].at[d, t], ind["r1w"].at[d, t]
            if X.get("trailing_stop", True) and p < s["peak"] * (1 - s["stop_pct"]):
                pending_exits[t] = ("all", 1.0, "trailing_stop")
            elif X.get("trend_exit", True) and pd.notna(ma200) and p < ma200 * (1 - X["ma200_buffer"]):
                pending_exits[t] = ("all", 1.0, "below_ma200")
            elif (PT.get("enabled", True) and not s["pt_done"] and pd.notna(r1w) and pd.notna(ma50)
                  and r1w >= PT["week_gain"] and p >= ma50 * (1 + PT["above_ma50"])):
                pending_exits[t] = ("frac", float(PT["fraction"]), "profit_take")

        if _is_decision_day(all_dates, d, P.get("rebalance_freq", "monthly")):
            held = {t: s["layer"] for t, s in pos.items()}
            exclude = {t for t, e in pending_exits.items() if e[0] == "all"}
            pending_rebal = pick_targets(d, px, ind, lidx, lind, uni, rules, held=held, exclude=exclude)
            for t in [t for t, e in pending_exits.items() if e[0] == "frac"]:
                del pending_exits[t]   # the rebalance re-sizes it anyway

    nav = pd.DataFrame(nav_rows).set_index("date")
    last = dates[-1]
    positions = []
    total = float(nav["nav"].iloc[-1])
    for t, s in pos.items():
        val = s["units"] * s["last_px"]
        positions.append({
            "ticker": t, "layer": s["layer"], "weight": val / total if total else 0.0,
            "entry_date": s["entry_date"], "entry_px": s["entry_px"], "price": s["last_px"],
            "pnl": s["last_px"] / s["entry_px"] - 1, "peak": s["peak"], "stop_pct": s["stop_pct"],
            "stop_level": s["peak"] * (1 - s["stop_pct"]), "dist_to_stop": s["last_px"] / (s["peak"] * (1 - s["stop_pct"])) - 1,
            "profit_take_done": s["pt_done"],
        })
    return {
        "nav": nav,
        "trades": pd.DataFrame(trades),
        "rebalances": rebalances,
        "positions": positions,
        "pending_exits": {t: {"kind": k, "fraction": f, "reason": r} for t, (k, f, r) in pending_exits.items()},
        "pending_rebalance": pending_rebal,
        "last_date": last,
    }


def simulate_equal_weight(px, uni, rules, start, end=None) -> pd.Series:
    """Benchmark: own every tradable stock in the chain equally, rebalanced monthly."""
    cost = float(rules["costs_per_side"])
    names = [t for t in stock_tickers(uni, active_only=True) if is_tradable(uni, t) and t in px.columns]
    all_dates = px.index
    end_ts = pd.Timestamp(end) if end else all_dates[-1]
    dates = all_dates[(all_dates >= pd.Timestamp(start)) & (all_dates <= end_ts)]
    i0 = all_dates.get_loc(dates[0])
    last_px: dict[str, float] = {}
    units: dict[str, float] = {}
    cash = 1.0
    pending = [t for t in names if pd.notna(px.at[all_dates[i0 - 1], t])]
    out = {}
    for d in dates:
        for t in names:
            p = px.at[d, t]
            if pd.notna(p):
                last_px[t] = float(p)
        if pending is not None:
            nav = cash + sum(u * last_px[t] for t, u in units.items())
            live = [t for t in pending if pd.notna(px.at[d, t])]
            if live:
                tgt = nav * (1 - cost) / len(live)
                new = {t: tgt / last_px[t] for t in live}
                turnover = sum(abs(new.get(t, 0.0) - units.get(t, 0.0)) * last_px[t] for t in set(new) | set(units))
                cash = nav - sum(new[t] * last_px[t] for t in new) - turnover * cost
                units = new
            pending = None
        out[d] = cash + sum(u * last_px[t] for t, u in units.items())
        if _next_trading_day(all_dates, d).month != d.month:
            pending = [t for t in names if pd.notna(px.at[d, t])]
    return pd.Series(out, name="equal_weight")


# ---------------------------------------------------------------- stats
def perf_stats(nav: pd.Series) -> dict:
    nav = nav.dropna()
    r = nav.pct_change().dropna()
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1 if years > 0 else float("nan")
    vol = float(r.std() * math.sqrt(252))
    sharpe = float(r.mean() / r.std() * math.sqrt(252)) if r.std() > 0 else float("nan")
    dd = float((nav / nav.cummax() - 1).min())
    monthly = nav.resample("ME").last().pct_change().dropna()
    return {
        "total_return": float(nav.iloc[-1] / nav.iloc[0] - 1),
        "cagr": float(cagr),
        "vol": vol,
        "sharpe": sharpe,
        "max_drawdown": dd,
        "calmar": float(cagr / abs(dd)) if dd < 0 else float("nan"),
        "worst_month": float(monthly.min()) if len(monthly) else float("nan"),
        "pct_positive_months": float((monthly > 0).mean()) if len(monthly) else float("nan"),
    }


def yearly_returns(nav: pd.Series) -> pd.Series:
    nav = nav.dropna()
    ends = nav.resample("YE").last()
    first = pd.Series([nav.iloc[0]], index=[nav.index[0] - pd.Timedelta(days=1)])
    return pd.concat([first, ends]).pct_change().dropna().set_axis(ends.index.year)
