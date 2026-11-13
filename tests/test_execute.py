import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from broker import BrokerError, FakeBroker  # noqa: E402
from execute import NY, plan_orders, session_check  # noqa: E402

G = {"max_order_pct": 0.35, "max_orders_per_run": 20, "min_order_usd": 25, "max_daily_turnover_pct": 2.1}
PX = {"AAA": 100.0, "BBB": 50.0, "CCC": 200.0, "OTHER": 10.0}
M = {"AAA", "BBB", "CCC"}


def pos(**q):
    return {t: {"qty": v, "price": PX[t], "value": v * PX[t]} for t, v in q.items()}


def run(book, positions, cash=100_000, capital=100_000):
    return plan_orders(book, capital, positions, PX.get, M, G, "2026-12-01", cash=cash)


def test_initial_buys_whole_shares():
    orders, _ = run({"mode": "initial", "targets": {"AAA": 0.3, "BBB": 0.2}}, {})
    assert {(o.ticker, o.side, o.qty) for o in orders} == {("AAA", "buy", 300), ("BBB", "buy", 400)}
    assert all(o.order_type == "moc" for o in orders)


def test_hold_mode_only_exits_and_never_resizes():
    book = {"mode": "hold", "targets": {"AAA": 0.9}, "exits": [{"ticker": "BBB", "reason": "trailing_stop"}]}
    orders, _ = run(book, pos(AAA=10, BBB=100), cash=0)
    assert [(o.ticker, o.side, o.qty, o.reason) for o in orders] == [("BBB", "sell", 100, "trailing_stop")]


def test_rebalance_band_and_rotation():
    book = {"mode": "rebalance", "rebalance_band": 0.05, "targets": {"AAA": 0.31, "CCC": 0.3}}
    orders, _ = run(book, pos(AAA=300, BBB=200), cash=60_000)
    got = {(o.ticker, o.side, o.qty) for o in orders}
    assert ("BBB", "sell", 200) in got          # rotated out
    assert ("CCC", "buy", 150) in got           # rotated in
    assert not any(o.ticker == "AAA" for o in orders)   # 1% off target < 5% band


def test_never_touches_foreign_positions():
    book = {"mode": "rebalance", "targets": {}}
    orders, _ = plan_orders(book, 100_000, {"OTHER": {"qty": 5, "price": 10, "value": 50}, **pos(AAA=10)},
                            PX.get, M, G, "2026-12-01", cash=0)
    assert [o.ticker for o in orders] == ["AAA"]


def test_buys_scaled_to_cash():
    orders, notes = run({"mode": "initial", "targets": {"AAA": 0.3, "BBB": 0.3}}, {}, cash=30_000)
    assert sum(o.notional for o in orders) <= 30_000
    assert any("scaled" in n for n in notes)


def test_oversized_order_blocked():
    orders, notes = run({"mode": "initial", "targets": {"AAA": 0.9}}, {})
    assert orders == [] and any("blocked" in n for n in notes)


def test_turnover_guard_raises():
    g = {**G, "max_daily_turnover_pct": 0.1}
    with pytest.raises(BrokerError):
        plan_orders({"mode": "initial", "targets": {"AAA": 0.3}}, 100_000, {}, PX.get, M, g, "d", cash=1e6)


def test_session_check():
    b = FakeBroker(days=["2026-11-25", "2026-11-27", "2026-11-30"])   # 26th = Thanksgiving
    at = lambda d, h=12: datetime.fromisoformat(d).replace(hour=h, tzinfo=NY)  # noqa: E731
    assert session_check(b, "2026-11-25", at("2026-11-27"), "15:45", "moc") is None
    assert "closed" in session_check(b, "2026-11-25", at("2026-11-26"), "15:45", "moc")
    assert "stale" in session_check(b, "2026-11-25", at("2026-11-30"), "15:45", "moc")
    assert "cutoff" in session_check(b, "2026-11-25", at("2026-11-27", 16), "15:45", "moc")
