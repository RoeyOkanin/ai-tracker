"""Snapshot of the broker account for the dashboard: docs/data/account.json.

Read-only: account value, cash, positions with P&L, the last orders and the daily
equity curve since the account opened. Runs after every trade run and after every
nightly switch decision. With no Alpaca keys it does nothing.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from broker import AlpacaBroker, BrokerError  # noqa: E402
from engine import DOCS_DATA, ROOT  # noqa: E402


def f(x, nd=2):
    try:
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


def main() -> int:
    if not os.environ.get("ALPACA_KEY_ID"):
        print("no Alpaca keys: no account snapshot")
        return 0
    cfg = yaml.safe_load((ROOT / "config" / "execution.yaml").read_text(encoding="utf-8"))
    paper = cfg.get("mode", "paper") != "live"
    b = AlpacaBroker(paper=paper)
    try:
        a = b.account()
        pos = b._req("GET", f"{b.base}/v2/positions")
        orders = b._req("GET", f"{b.base}/v2/orders", params={"status": "all", "limit": 15, "direction": "desc"})
        hist = b._req("GET", f"{b.base}/v2/account/portfolio/history",
                      params={"period": "1A", "timeframe": "1D", "intraday_reporting": "market_hours"})
    except BrokerError as e:
        print(f"account snapshot failed: {e}")
        return 0

    equity, last_eq = f(a.get("equity")), f(a.get("last_equity"))
    start = float(cfg.get("paper_start_usd") or 100_000)
    ts, eq = hist.get("timestamp") or [], hist.get("equity") or []
    curve = [(datetime.fromtimestamp(t, timezone.utc).date().isoformat(), f(v)) for t, v in zip(ts, eq) if v]
    out = {
        "as_of_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "broker": "alpaca", "paper": paper, "currency": a.get("currency", "USD"),
        "equity": equity, "cash": f(a.get("cash")), "last_equity": last_eq,
        "start_equity": start,
        "pnl_total": f(equity - start) if equity is not None else None,
        "pnl_total_pct": f(equity / start - 1, 4) if equity else None,
        "pnl_today": f(equity - last_eq) if equity is not None and last_eq else None,
        "pnl_today_pct": f(equity / last_eq - 1, 4) if equity and last_eq else None,
        "invested_pct": f(1 - float(a.get("cash", 0)) / equity, 4) if equity else None,
        "positions": sorted([{
            "ticker": p["symbol"], "qty": f(p["qty"], 4), "price": f(p.get("current_price")),
            "avg_entry": f(p.get("avg_entry_price")), "value": f(p.get("market_value")),
            "weight": f(float(p.get("market_value") or 0) / equity, 4) if equity else None,
            "pnl": f(p.get("unrealized_pl")), "pnl_pct": f(p.get("unrealized_plpc"), 4),
            "pnl_today_pct": f(p.get("change_today"), 4),
        } for p in pos], key=lambda x: -(x["value"] or 0)),
        "orders": [{
            "date": (o.get("filled_at") or o.get("submitted_at") or "")[:10], "ticker": o.get("symbol"),
            "side": o.get("side"), "qty": f(o.get("filled_qty") or o.get("qty"), 4), "type": o.get("type"),
            "tif": o.get("time_in_force"), "status": o.get("status"), "price": f(o.get("filled_avg_price")),
        } for o in orders],
        "history": {"dates": [d for d, _ in curve], "equity": [v for _, v in curve]},
    }
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    (DOCS_DATA / "account.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"account: equity ${equity:,.0f}, cash ${out['cash']:,.0f}, {len(out['positions'])} positions, "
          f"{len(out['orders'])} recent orders, {len(curve)} days of history")
    return 0


if __name__ == "__main__":
    sys.exit(main())
