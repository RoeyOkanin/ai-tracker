"""Broker adapters. The executor only talks to the Broker interface, so adding
Interactive Brokers later means one new class here, nothing else.

Alpaca is called over plain REST (no SDK) to keep the dependency list short.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import requests


@dataclass
class Order:
    ticker: str
    side: str            # buy | sell
    qty: float
    reason: str
    est_price: float
    client_id: str
    order_type: str = "moc"

    @property
    def notional(self) -> float:
        return self.qty * self.est_price


class BrokerError(RuntimeError):
    pass


class Broker:
    name = "base"
    paper = True

    def equity(self) -> float: ...
    def cash(self) -> float: ...
    def positions(self) -> dict[str, dict]: ...          # ticker -> {"qty", "price", "value"}
    def last_price(self, ticker: str) -> float | None: ...
    def trading_days(self, start: str, end: str) -> list[str]: ...
    def open_orders(self) -> list[dict]: ...
    def submit(self, order: Order) -> dict: ...


class AlpacaBroker(Broker):
    name = "alpaca"
    PAPER_URL = "https://paper-api.alpaca.markets"
    LIVE_URL = "https://api.alpaca.markets"
    DATA_URL = "https://data.alpaca.markets"

    def __init__(self, paper: bool = True, key: str | None = None, secret: str | None = None):
        self.paper = paper
        self.base = self.PAPER_URL if paper else self.LIVE_URL
        key = key or os.environ.get("ALPACA_KEY_ID")
        secret = secret or os.environ.get("ALPACA_SECRET_KEY")
        if not key or not secret:
            raise BrokerError("missing ALPACA_KEY_ID / ALPACA_SECRET_KEY")
        self.s = requests.Session()
        self.s.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
        self._acct = None

    def _req(self, method: str, url: str, **kw):
        for attempt in range(4):
            r = self.s.request(method, url, timeout=20, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                raise BrokerError(f"{method} {url} -> {r.status_code}: {r.text[:300]}")
            return r.json() if r.content else {}
        raise BrokerError(f"{method} {url} failed after retries")

    def account(self) -> dict:
        if self._acct is None:
            self._acct = self._req("GET", f"{self.base}/v2/account")
            if self._acct.get("trading_blocked") or self._acct.get("account_blocked"):
                raise BrokerError("account is blocked for trading")
        return self._acct

    def equity(self) -> float:
        return float(self.account()["equity"])

    def cash(self) -> float:
        return float(self.account()["cash"])

    def positions(self) -> dict[str, dict]:
        out = {}
        for p in self._req("GET", f"{self.base}/v2/positions"):
            out[p["symbol"]] = {"qty": float(p["qty"]), "price": float(p["current_price"]),
                                "value": float(p["market_value"])}
        return out

    def last_price(self, ticker: str) -> float | None:
        try:
            j = self._req("GET", f"{self.DATA_URL}/v2/stocks/{ticker}/trades/latest", params={"feed": "iex"})
            return float(j["trade"]["p"])
        except (BrokerError, KeyError, TypeError, ValueError):
            return None

    def trading_days(self, start: str, end: str) -> list[str]:
        return [d["date"] for d in self._req("GET", f"{self.base}/v2/calendar", params={"start": start, "end": end})]

    def open_orders(self) -> list[dict]:
        return self._req("GET", f"{self.base}/v2/orders", params={"status": "open", "limit": 500})

    def submit(self, order: Order) -> dict:
        body = {"symbol": order.ticker, "qty": str(order.qty), "side": order.side, "type": "market",
                "time_in_force": "cls" if order.order_type == "moc" else "day",
                "client_order_id": order.client_id}
        return self._req("POST", f"{self.base}/v2/orders", json=body)


@dataclass
class FakeBroker(Broker):
    """In-memory broker for dry runs and tests."""
    cash_usd: float = 100_000.0
    holdings: dict[str, float] = field(default_factory=dict)
    prices: dict[str, float] = field(default_factory=dict)
    days: list[str] = field(default_factory=list)
    submitted: list[Order] = field(default_factory=list)
    name: str = "fake"
    paper: bool = True

    def equity(self) -> float:
        return self.cash_usd + sum(q * self.prices.get(t, 0.0) for t, q in self.holdings.items())

    def cash(self) -> float:
        return self.cash_usd

    def positions(self) -> dict[str, dict]:
        return {t: {"qty": q, "price": self.prices.get(t, 0.0), "value": q * self.prices.get(t, 0.0)}
                for t, q in self.holdings.items() if q}

    def last_price(self, ticker: str) -> float | None:
        return self.prices.get(ticker)

    def trading_days(self, start: str, end: str) -> list[str]:
        return [d for d in self.days if start <= d <= end]

    def open_orders(self) -> list[dict]:
        return [{"client_order_id": o.client_id, "symbol": o.ticker} for o in self.submitted]

    def submit(self, order: Order) -> dict:
        if any(o.client_id == order.client_id for o in self.submitted):
            raise BrokerError("duplicate client_order_id")
        self.submitted.append(order)
        sign = 1 if order.side == "buy" else -1
        self.holdings[order.ticker] = self.holdings.get(order.ticker, 0.0) + sign * order.qty
        self.cash_usd -= sign * order.qty * order.est_price
        return {"id": f"fake-{len(self.submitted)}", "status": "accepted"}
