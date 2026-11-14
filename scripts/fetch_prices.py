"""Downloads daily adjusted closes for the whole universe into data/prices.csv.

Runs in GitHub Actions after the US close. It re-downloads the full history on
every run, so dividend and split adjustments always stay consistent.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from engine import DATA, all_tickers, drop_partial_session, load_config

START = "2017-06-01"


def _closes(frame: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        if "Close" in frame.columns.get_level_values(0):
            out = frame["Close"]
        else:
            out = frame.xs("Close", axis=1, level=1)
    else:
        out = frame[["Close"]].rename(columns={"Close": tickers[0]})
    out = out.copy()
    out.index = pd.to_datetime(pd.Index(out.index).map(lambda x: x.date() if hasattr(x, "date") else x))
    return out


def bulk_download(tickers: list[str]) -> pd.DataFrame:
    err = None
    for attempt in range(4):
        try:
            raw = yf.download(tickers, start=START, auto_adjust=True, progress=False,
                              group_by="column", threads=True)
            close = _closes(raw, tickers)
            if not close.empty:
                return close
        except Exception as e:  # network / rate limit
            err = e
        time.sleep(20 * (attempt + 1))
    print(f"bulk download failed: {err}", file=sys.stderr)
    return pd.DataFrame()


def single_download(t: str) -> pd.Series | None:
    for attempt in range(3):
        try:
            h = yf.Ticker(t).history(start=START, auto_adjust=True)
            if h is not None and not h.empty:
                s = h["Close"].copy()
                s.index = pd.to_datetime([x.date() for x in s.index])
                return s.rename(t)
        except Exception as e:
            print(f"{t}: {e}", file=sys.stderr)
        time.sleep(10 * (attempt + 1))
    return None


def main() -> int:
    uni, _ = load_config()
    tickers = all_tickers(uni)
    prev_path = DATA / "prices.csv"
    prev = pd.read_csv(prev_path, index_col=0, parse_dates=True) if prev_path.exists() else None

    close = bulk_download(tickers)
    for t in tickers:  # second chance, one by one
        if t not in close.columns or close[t].notna().sum() == 0:
            s = single_download(t)
            if s is not None:
                close = close.drop(columns=[t], errors="ignore").join(s, how="outer")

    # keep the old column for any ticker that failed today
    if prev is not None:
        for t in tickers:
            if (t not in close.columns or close[t].notna().sum() == 0) and t in prev.columns:
                close = close.drop(columns=[t], errors="ignore").join(prev[t], how="outer")

    # never store a half-finished US session
    close = drop_partial_session(close)

    close = close.reindex(columns=[t for t in tickers if t in close.columns]).sort_index()
    close = close.dropna(how="all")

    valid = [t for t in close.columns if close[t].notna().sum() > 0]
    if prev is not None:
        prev_valid = [t for t in prev.columns if prev[t].notna().sum() > 0]
        if len(valid) < 0.8 * len(prev_valid):
            print(f"only {len(valid)} tickers came back (had {len(prev_valid)}); keeping old file", file=sys.stderr)
            return 1
    if len(valid) == 0:
        print("no data at all", file=sys.stderr)
        return 1

    DATA.mkdir(parents=True, exist_ok=True)
    close.to_csv(prev_path, float_format="%.4f")

    report = {
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_date": str(close.index[-1].date()),
        "missing": [t for t in tickers if t not in valid],
        "tickers": {
            t: {
                "first": str(close[t].first_valid_index().date()),
                "last": str(close[t].last_valid_index().date()),
                "rows": int(close[t].notna().sum()),
            }
            for t in valid
        },
    }
    (DATA / "fetch_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"saved {len(valid)}/{len(tickers)} tickers through {report['last_date']}; missing: {report['missing']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
