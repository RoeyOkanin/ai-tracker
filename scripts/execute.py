"""Turns a target book into broker orders.

Which book is set by `book:` in config/execution.yaml (or --book):
  switch    docs/data/switch_target_book.json  (switch_live.py, the main strategy)
  rotation  docs/data/target_book.json         (compute.py, the 93-company rotation)

    python scripts/execute.py --broker alpaca          # automatic (paper unless execution.yaml says live)
    python scripts/execute.py --broker ticket          # manual broker (Colmex): writes an order ticket, sends nothing
    python scripts/execute.py --broker fake --dry-run  # local test, no keys needed

The book is written by compute.py after a close and describes the account
after the NEXT close. Orders go out as market-on-close, so fills land on the
same price the backtest assumes.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from broker import AlpacaBroker, Broker, BrokerError, FakeBroker, Order  # noqa: E402
from engine import DATA, DOCS_DATA, ROOT, load_config, stock_tickers  # noqa: E402

NY = ZoneInfo("America/New_York")
LOG_FIELDS = ["run_utc", "exec_date", "broker", "paper", "ticker", "side", "qty", "est_price", "notional",
              "reason", "status", "detail"]
REASON_HE = {"exit": "יציאה (סטופ / ממוצע 200)", "rebalance_out": "יוצאת באיזון", "rebalance_in": "נכנסת באיזון",
             "rebalance_add": "הגדלה באיזון", "rebalance_trim": "הקטנה באיזון", "initial": "פתיחת תיק",
             "sync": "סנכרון לתיק היעד", "trailing_stop": "נשבר הסטופ הנגרר", "below_ma200": "מתחת לממוצע 200"}


def load_exec_config() -> dict:
    return yaml.safe_load((ROOT / "config" / "execution.yaml").read_text(encoding="utf-8"))


def whole(x: float) -> int:
    return int(math.floor(x + 1e-9))


def plan_orders(book: dict, capital: float, positions: dict[str, dict], price_of, managed: set[str],
                guards: dict, exec_date: str, order_type: str = "moc", cash: float | None = None) -> tuple[list[Order], list[str]]:
    """Pure function: book + account -> orders. Whole shares only (MOC can't do fractions).
    Returns (orders, skipped notes)."""
    notes: list[str] = []
    mode = book.get("mode", "none")
    if mode == "none":
        return [], ["no book for this session (portfolio not started)"]
    targets = {t: float(w) for t, w in book.get("targets", {}).items()}
    exit_reason = {e["ticker"]: e["reason"] for e in book.get("exits", [])}
    band = float(book.get("rebalance_band", 0.05)) * capital
    held = {t: p for t, p in positions.items() if t in managed and abs(p["qty"]) > 0}

    def cid(t, side):
        return f"ait-{exec_date}-{t}-{side}"[:48]

    sells, buys = [], []
    for t, p in held.items():
        if t not in targets:
            reason = exit_reason.get(t, "rebalance_out" if mode in ("rebalance", "initial") else "sync")
            sells.append(Order(t, "sell", whole(p["qty"]), reason, price_of(t) or p["price"], cid(t, "sell"), order_type))

    for t, w in targets.items():
        px = price_of(t)
        if not px or px <= 0:
            notes.append(f"{t}: no price, skipped")
            continue
        cur = held.get(t, {}).get("qty", 0.0) * px
        want = w * capital
        if t in held and mode == "hold":
            continue                      # between rebalances positions drift, like the paper portfolio
        if t in held and abs(want - cur) < band:
            continue
        diff = want - cur
        q = whole(abs(diff) / px)
        if q <= 0:
            if t not in held:
                notes.append(f"{t}: target ${want:,.0f} is less than one share (${px:,.0f}), skipped")
            continue
        if diff < 0:
            sells.append(Order(t, "sell", q, "rebalance_trim", px, cid(t, "sell"), order_type))
        else:
            reason = "initial" if mode == "initial" else ("rebalance_add" if t in held else
                                                           ("rebalance_in" if mode == "rebalance" else "sync"))
            buys.append(Order(t, "buy", q, reason, px, cid(t, "buy"), order_type))

    # buys only with money we have: free cash + what the sells bring in (both fill at the same close)
    if cash is not None and buys:
        budget = cash + sum(o.notional for o in sells) * 0.995
        need = sum(o.notional for o in buys)
        if need > budget > 0:
            scale = budget / need
            for o in buys:
                o.qty = whole(o.qty * scale)
            notes.append(f"buys scaled to {scale:.0%} to fit cash")
        elif budget <= 0:
            notes.append("no cash for buys")
            buys = []

    orders = [o for o in sells + buys if o.qty > 0]
    out = []
    for o in orders:
        if o.notional < guards.get("min_order_usd", 0):
            notes.append(f"{o.ticker}: ${o.notional:.0f} under the minimum, skipped")
            continue
        cap = guards.get("etf_max_order_pct", 1.0) if o.ticker in guards.get("etfs", ()) else guards.get("max_order_pct", 1.0)
        if o.notional > cap * capital * 1.02 and o.side == "buy":
            notes.append(f"{o.ticker}: ${o.notional:.0f} above max_order_pct, blocked")
            continue
        out.append(o)
    if len(out) > guards.get("max_orders_per_run", 99):
        raise BrokerError(f"{len(out)} orders > max_orders_per_run; refusing to trade")
    turnover = sum(o.notional for o in out)
    if capital > 0 and turnover > guards.get("max_daily_turnover_pct", 9.0) * capital:
        raise BrokerError(f"turnover {turnover / capital:.0%} of capital > limit; refusing to trade")
    return out, notes


def session_check(broker: Broker, signal_date: str, now_ny: datetime, cutoff: str, order_type: str) -> str | None:
    """None if today is the session the book was written for, otherwise the reason not to trade."""
    today = now_ny.date().isoformat()
    days = broker.trading_days(signal_date, today)
    after = [d for d in days if d > signal_date]
    if not after or after[0] != today:
        if today not in days:
            return f"market closed today ({today})"
        return f"stale book: it was made for {after[0] if after else signal_date} (a newer close exists), today is {today}"
    if order_type == "moc":
        h, m = map(int, cutoff.split(":"))
        if (now_ny.hour, now_ny.minute) >= (h, m):
            return f"past the MOC cutoff ({cutoff} New York)"
    return None


def append_log(rows: list[dict]) -> None:
    path = DATA / "execution_log.csv"
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)


BOOKS = {"switch": "switch_target_book.json", "rotation": "target_book.json"}


def last_closes(book: dict | None = None) -> dict[str, float]:
    if book and book.get("last_close"):
        return {t: float(v) for t, v in book["last_close"].items()}
    px = pd.read_csv(DATA / "prices.csv", index_col=0)
    last = px.ffill().iloc[-1]
    return {str(k): float(v) for k, v in last.items() if pd.notna(v)}


# ------------------------------------------------------------ manual broker (Colmex): a ticket + a shadow book
MANUAL_BOOK = DATA / "manual_book.json"   # per book: manual_book_switch.json for the switch


def manual_broker(capital: float, book: dict | None = None) -> FakeBroker:
    closes = last_closes(book)
    if MANUAL_BOOK.exists():
        st = json.loads(MANUAL_BOOK.read_text(encoding="utf-8"))
        return FakeBroker(cash_usd=st["cash"], holdings=st["holdings"], prices=closes, name="ticket")
    return FakeBroker(cash_usd=capital, prices=closes, name="ticket")


def save_manual(b: FakeBroker, exec_date: str) -> None:
    MANUAL_BOOK.write_text(json.dumps({"assumed_filled_for": exec_date, "cash": round(b.cash_usd, 2),
                                       "holdings": {t: q for t, q in b.holdings.items() if q}}, indent=1),
                           encoding="utf-8")


def ticket_markdown(orders: list[Order], exec_date: str, book: dict, notes: list[str]) -> str:
    lines = [f"### 🧾 פקודות לביצוע ידני ב-Colmex: סגירה של {exec_date}",
             "שלח כ-**MOC** (Market On Close). אם אין, שלח Market בעשר הדקות האחרונות לפני הסגירה (23:50 שעון ישראל, 22:50 בקיץ האמריקאי).", "",
             "| מניה | פעולה | כמות | מחיר משוער | סכום | סיבה |", "|---|---|---|---|---|---|"]
    for o in orders:
        lines.append(f"| **{o.ticker}** | {'קנייה' if o.side == 'buy' else 'מכירה'} | {o.qty} | ${o.est_price:,.2f} | "
                     f"${o.notional:,.0f} | {REASON_HE.get(o.reason, o.reason)} |")
    if notes:
        lines += ["", "הערות: " + "; ".join(notes)]
    lines += ["", f"מצב: {book.get('regime') or book.get('hold')}. מכירות לפני קניות. אם לא ביצעת, כתוב בגיטהאב issue ונסנכרן."]
    return "\n".join(lines)


# ------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", choices=["alpaca", "ticket", "fake"], default=None)
    ap.add_argument("--dry-run", action="store_true", help="plan and print, send nothing")
    ap.add_argument("--book", choices=sorted(BOOKS), default=None, help="which target book to execute")
    ap.add_argument("--force-date", help="treat this YYYY-MM-DD as today (tests / catching up)")
    args = ap.parse_args(argv)

    cfg = load_exec_config()
    broker_name = args.broker or cfg.get("broker", "alpaca")
    book_name = args.book or cfg.get("book", "rotation")
    book_path = DOCS_DATA / BOOKS[book_name]
    if not book_path.exists():
        print(f"no {book_path.name} yet; run {'switch_live.py' if book_name == 'switch' else 'compute.py'} first")
        return 0
    book = json.loads(book_path.read_text(encoding="utf-8"))
    global MANUAL_BOOK
    if book_name != "rotation":
        MANUAL_BOOK = DATA / f"manual_book_{book_name}.json"
    if not cfg["guards"].get("only_universe_tickers", True):
        managed = set()
    elif book.get("managed"):
        managed = set(book["managed"])            # the switch: whole physical chain + SMH
    else:
        uni, _ = load_config()
        managed = set(stock_tickers(uni))
    now_ny = datetime.now(NY)
    run_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    order_type = cfg.get("order_type", "moc")
    notify_path = os.environ.get("NOTIFY_PATH")

    if broker_name == "ticket":
        capital = float(cfg.get("manual_capital_usd") or cfg.get("allocation_usd") or 10_000)
        b = manual_broker(capital, book)
        exec_date = (pd.Timestamp(book["signal_date"]) + pd.offsets.BDay(1)).date().isoformat()
        managed = managed or set(b.holdings)
    else:
        paper = cfg.get("mode", "paper") != "live"
        if not paper and os.environ.get("LIVE_TRADING_CONFIRM") != "YES":
            print("REFUSING: execution.yaml says live but LIVE_TRADING_CONFIRM secret is not YES")
            return 2
        if broker_name == "alpaca":
            b = AlpacaBroker(paper=paper)
        else:
            closes = last_closes(book)
            b = FakeBroker(prices=closes, days=[d.date().isoformat() for d in pd.bdate_range("2026-01-01", "2027-12-31")])
        if args.force_date:
            now_ny = datetime.fromisoformat(args.force_date).replace(hour=12, tzinfo=NY)
        acct = b.positions()
        print(f"account {b.name} ({'paper' if b.paper else 'LIVE'}): equity ${b.equity():,.0f}, cash ${b.cash():,.0f}, "
              f"{len(acct)} positions ({len([t for t in acct if t in managed])} managed by this book)")
        why = session_check(b, book["signal_date"], now_ny, cfg.get("moc_cutoff_et", "15:45"), order_type)
        if why:
            print(f"not trading: {why}")
            if notify_path and "market closed" not in why:
                with open(notify_path, "a", encoding="utf-8") as f:
                    f.write(f"### ⚠️ לא נשלחו פקודות היום ({now_ny.date()})\n{why}.\n"
                            f"הספר האחרון: {book['signal_date']} ({book.get('mode')}). "
                            "כנראה שהריצה הלילית (daily-update או switch-strategy) נכשלה או לא עלתה לריפו. "
                            "בדוק בלשונית Actions.\n")
            return 0
        exec_date = now_ny.date().isoformat()
        alloc = cfg.get("allocation_usd")
        capital = min(b.equity(), float(alloc)) if alloc else b.equity()

    positions = b.positions()
    orders, notes = plan_orders(book, capital, positions, b.last_price, managed or set(positions),
                                cfg["guards"], exec_date, order_type, cash=b.cash())
    print(f"{broker_name} | book {book['signal_date']} ({book['mode']}) -> {exec_date} | capital ${capital:,.0f} | "
          f"{len(orders)} orders")
    for o in orders:
        print(f"  {o.side:4} {o.qty:>6} {o.ticker:<8} ~${o.notional:>10,.0f}  {o.reason}")
    for n in notes:
        print(f"  note: {n}")

    if broker_name == "ticket":
        if orders and not args.dry_run:
            for o in orders:
                b.submit(o)
            save_manual(b, exec_date)
            if notify_path:
                with open(notify_path, "a", encoding="utf-8") as f:
                    f.write("\n" + ticket_markdown(orders, exec_date, book, notes) + "\n")
        return 0

    if not cfg.get("enabled", True) or args.dry_run:
        print("dry run / kill switch: nothing sent")
        return 0

    already = {o.get("client_order_id") for o in b.open_orders()}
    rows, failed = [], 0
    for o in orders:
        status, detail = "sent", ""
        if o.client_id in already:
            status = "already_open"
        else:
            try:
                detail = b.submit(o).get("id", "")
            except BrokerError as e:
                status, detail, failed = "error", str(e)[:200], failed + 1
        rows.append({"run_utc": run_utc, "exec_date": exec_date, "broker": b.name, "paper": b.paper,
                     **{k: v for k, v in asdict(o).items() if k in ("ticker", "side", "qty", "est_price", "reason")},
                     "notional": round(o.notional, 2), "status": status, "detail": detail})
    if rows:
        append_log(rows)
    if notify_path and rows:
        tag = "נייר" if b.paper else "כסף אמיתי"
        with open(notify_path, "a", encoding="utf-8") as f:
            f.write(f"### 🤖 נשלחו {len(rows) - failed} פקודות MOC ל-{b.name} ({tag}), סגירה של {exec_date}\n")
            for r in rows:
                f.write(f"- {r['side']} {r['qty']} **{r['ticker']}** (~${r['notional']:,.0f}) {r['reason']}: {r['status']}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
