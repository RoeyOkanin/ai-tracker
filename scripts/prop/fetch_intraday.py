"""Fetch intraday bars for the prop-firm strategy research.

QQQ/SPY 5-minute bars 2016+ from Alpaca's market-data API (SIP, free tier allows
historical SIP older than 15 minutes), plus NQ=F / ES=F hourly from yfinance as a
futures sanity check (yfinance caps 1h history at ~730 days).
"""
import os, time, pathlib
import pandas as pd, requests

OUT = pathlib.Path(__file__).resolve().parents[2] / "data" / "prop"
OUT.mkdir(parents=True, exist_ok=True)
H = {"APCA-API-KEY-ID": os.environ.get("ALPACA_KEY_ID", ""),
     "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", "")}


def alpaca(sym, tf="5Min", start="2016-01-01", feed="sip"):
    url = f"https://data.alpaca.markets/v2/stocks/{sym}/bars"
    p = {"timeframe": tf, "start": start, "limit": 10000, "adjustment": "all", "feed": feed}
    rows = []
    while True:
        r = requests.get(url, headers=H, params=p, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"{sym} {r.status_code} {r.text[:300]}")
        j = r.json()
        rows += j.get("bars") or []
        tok = j.get("next_page_token")
        if not tok:
            break
        p["page_token"] = tok
        time.sleep(0.35)
    df = pd.DataFrame(rows).rename(columns={"t": "ts", "o": "open", "h": "high", "l": "low",
                                            "c": "close", "v": "volume", "vw": "vwap"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("America/New_York")
    return df[["ts", "open", "high", "low", "close", "volume", "vwap"]]


for sym in ["QQQ", "SPY", "IWM", "DIA", "GLD", "USO"]:
    if (OUT / f"{sym}_5m.csv.gz").exists():
        continue
    for feed in ["sip", "iex"]:
        try:
            df = alpaca(sym, feed=feed)
            df.to_csv(OUT / f"{sym}_5m.csv.gz", index=False)
            print(sym, feed, len(df), df.ts.iloc[0], df.ts.iloc[-1])
            break
        except Exception as e:
            print("fail", sym, feed, e)

try:
    import yfinance as yf
    if (OUT / "NQ_1h.csv.gz").exists():
        raise SystemExit(0)
    for t in ["NQ=F", "ES=F"]:
        d = yf.download(t, interval="1h", period="730d", progress=False, auto_adjust=False)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        d.to_csv(OUT / f"{t.replace('=F','')}_1h.csv.gz")
        print(t, len(d))
        d = yf.download(t, interval="5m", period="60d", progress=False, auto_adjust=False)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        d.to_csv(OUT / f"{t.replace('=F','')}_5m.csv.gz")
        print(t, "5m", len(d))
except Exception as e:
    print("yf fail", e)
