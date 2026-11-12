"""News radar: collects headlines for every company and every bottleneck theme,
counts shortage language vs easing language, and scores each layer.

Sources (no API keys): Google News RSS search, plus Yahoo Finance news via yfinance.
Runs in GitHub Actions after the price download. It never fails the job:
a bad news day only means fewer headlines.

Outputs
  data/news/items/YYYY-MM-DD.jsonl  new matched headlines first seen that day (append-only)
  data/news/layer_signals.csv       per published day and layer: items, tight, ease, friction
  data/news/stock_signals.csv       per published day and ticker: items, tight, ease, friction
  data/news/seen.json               ids already counted (last 14 days), so nothing is counted twice
  docs/data/radar.json              per-layer pressure, weekly heat map, top headlines (dashboard)
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

import pandas as pd

from engine import DATA, DOCS_DATA, layer_members, layer_names, load_config

NEWS = DATA / "news"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ai-tracker/1.0"}
SUPPLY_TERMS = ('(shortage OR "sold out" OR "supply constrained" OR "lead times" OR backlog OR "price increase" '
                'OR "price hike" OR "raise prices" OR oversupply OR glut OR "inventory correction" OR "price cut" '
                'OR capacity OR allocation)')

# Language that says "supply is tight" (bottleneck forming or alive)
TIGHT = [
    r"\bshortages?\b", r"\bsold[- ]out\b", r"\bsells? out\b", r"supply[- ]constrain", r"capacity[- ]constrain",
    r"\btight(?:er|ening)? supply\b", r"\bsupply (?:is |remains |stays )?tight", r"\bsupply crunch\b",
    r"\bbottlenecks?\b", r"lead[- ]times? (?:extend|lengthen|stretch|rise|grow|balloon)", r"longer lead[- ]times?",
    r"\brecord backlog\b", r"backlog (?:hits|reaches|swells|grows|jumps|surges|climbs)", r"\ballocation\b",
    r"\bprice (?:hikes?|increases?)\b", r"\brais(?:e|es|ed|ing) (?:\w+ ){0,2}prices\b", r"\bhik(?:e|es|ed|ing) (?:\w+ ){0,2}prices\b",
    r"\bprices? (?:\w+ ){0,4}(?:surg|soar|jump|climb|ris|spik|skyrocket)\w*", r"demand (?:outstrips|outpaces|exceeds) supply",
    r"\bprepay", r"\bbooked (?:through|until|out)\b", r"can'?t keep up", r"\brationing\b", r"\bscarcit", r"\bscarce\b",
]
# Language that says "the shortage is ending" (time to let go)
EASE = [
    r"\boversuppl", r"\bglut\b", r"inventory (?:correction|build|glut|digestion)", r"excess inventor",
    r"\bprice (?:cuts?|declines?|drops?|falls?|war)\b", r"\bprices? (?:\w+ ){0,3}(?:fall|drop|slump|plung|declin|soften|eas|slid)\w*",
    r"double[- ]order", r"order (?:cuts|cancellations)", r"cancel(?:s|led|ling)? orders",
    r"shortage (?:eases|easing|ends|is over|to end)", r"supply (?:eases|easing|loosens|improves)",
    r"demand (?:slows|softens|weakens|cools)", r"capacity (?:expansion|additions?|surge|ramp)", r"\bnew fab\b",
    # the rate of improvement turning down: the stage where you let go
    r"\bslow(?:er|ing|s)? (?:price )?(?:gains|increases|growth)\b", r"\b(?:gains|increases) (?:narrow|moderate|slow)\w*",
    r"\bpace\b.{0,60}?\b(?:moderat|slow)\w*",
]
# Politics, permits and financing friction (a non-physical bottleneck)
FRICTION = [r"\bmoratori", r"\bpermit", r"\bzoning\b", r"\bballot\b", r"\bbacklash\b", r"\bopposition\b",
            r"\bcredit spreads?\b", r"\bdowngrade", r"\bfinancing (?:risk|concerns?|stress)"]
TIGHT_RX = [re.compile(p, re.I) for p in TIGHT]
EASE_RX = [re.compile(p, re.I) for p in EASE]
FRICTION_RX = [re.compile(p, re.I) for p in FRICTION]
STOCKY = re.compile(r"\b(?:stocks?|shares|price target|fair value|valuation|market cap|rall(?:y|ies)|sell-?off|buy the dip|bargain)\b", re.I)
PRICE_DIRECTION = re.compile(r"prices?\b(?!.*\b(?:hike|increase)).{0,40}\b(?:surg|soar|jump|climb|ris|spik|skyrocket|fall|drop|slump|plung|declin|soften|eas|slid)", re.I)
NEGATED = re.compile(r"\b(?:no|not|without|avoid(?:s|ed)?|ease[sd]?|easing|end(?:s|ed)?)\b[\w\s,'-]{0,18}$", re.I)


def score(text: str) -> dict:
    """Counts tight / ease / friction phrases in a headline (each capped at 2)."""
    t = " " + (text or "") + " "
    stocky = bool(STOCKY.search(t))
    tags: list[str] = []
    ease = 0
    for rx in EASE_RX:
        m = rx.search(t)
        if m and stocky and PRICE_DIRECTION.search(m.group(0)):
            continue   # "stock price falls" is not "product prices fall"
        if m:
            ease += 1
            tags.append(m.group(0).lower())
            t = t[: m.start()] + " " * (m.end() - m.start()) + t[m.end():]   # don't count it again as tight
    tight = 0
    for rx in TIGHT_RX:
        m = rx.search(t)
        if m and stocky and PRICE_DIRECTION.search(m.group(0)):
            continue
        if m and not NEGATED.search(t[: m.start()]):
            tight += 1
            tags.append(m.group(0).lower())
    friction = sum(1 for rx in FRICTION_RX if rx.search(t))
    return {"tight": min(tight, 2), "ease": min(ease, 2), "friction": min(friction, 1), "tags": tags[:4]}


def item_id(title: str) -> str:
    norm = re.sub(r"[^a-z0-9 ]+", "", (title or "").lower())
    return hashlib.sha1(re.sub(r"\s+", " ", norm).strip().encode()).hexdigest()[:16]


def _get(url: str, timeout: int = 20) -> bytes | None:
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:
            if attempt == 2:
                print(f"  fetch failed: {url[:90]}… {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def parse_google_rss(xml_bytes: bytes) -> list[dict]:
    out = []
    root = ET.fromstring(xml_bytes)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = it.find("source")
        source = (src.text or "").strip() if src is not None else ""
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)].strip()
        pub = it.findtext("pubDate")
        try:
            published = parsedate_to_datetime(pub).astimezone(timezone.utc) if pub else None
        except (TypeError, ValueError):
            published = None
        out.append({"title": html.unescape(title), "source": source, "url": (it.findtext("link") or "").strip(),
                    "published": published, "text": ""})
    return out


def google_news(query: str, days: int) -> list[dict] | None:
    url = ("https://news.google.com/rss/search?q=" + quote_plus(f"{query} when:{days}d")
           + "&hl=en-US&gl=US&ceid=US:en")
    raw = _get(url)
    if raw is None:
        return None
    try:
        return parse_google_rss(raw)
    except ET.ParseError:
        return None


def parse_yahoo_items(items: list) -> list[dict]:
    out = []
    for n in items or []:
        c = n.get("content", n) if isinstance(n, dict) else {}
        title = c.get("title") or ""
        if not title:
            continue
        pub = c.get("pubDate") or c.get("displayTime") or n.get("providerPublishTime")
        try:
            published = (datetime.fromtimestamp(pub, tz=timezone.utc) if isinstance(pub, (int, float))
                         else pd.Timestamp(pub).tz_convert("UTC").to_pydatetime() if pub else None)
        except Exception:
            published = None
        provider = (c.get("provider") or {}).get("displayName") if isinstance(c.get("provider"), dict) else None
        url = ((c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else None) \
            or ((c.get("clickThroughUrl") or {}).get("url") if isinstance(c.get("clickThroughUrl"), dict) else None) \
            or n.get("link") or ""
        out.append({"title": title.strip(), "source": provider or n.get("publisher") or "Yahoo Finance", "url": url,
                    "published": published, "text": c.get("summary") or c.get("description") or ""})
    return out


def yahoo_news(ticker: str) -> list[dict] | None:
    try:
        import yfinance as yf
        return parse_yahoo_items(yf.Ticker(ticker).news)
    except Exception as e:
        print(f"  yahoo news failed for {ticker}: {e}", file=sys.stderr)
        return None


def upsert(path, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Adds counts for (date, key) rows that already exist, appends the rest."""
    vals = ["items", "tight", "ease", "friction"]
    if path.exists():
        old = pd.read_csv(path, dtype={k: str for k in keys})
        both = pd.concat([old, new], ignore_index=True)
    else:
        both = new
    both = both.groupby(keys, as_index=False)[vals].sum().sort_values(keys)
    both.to_csv(path, index=False)
    return both


def build_radar(uni, layer_sig: pd.DataFrame, stock_sig: pd.DataFrame, today: datetime) -> dict:
    names = layer_names(uni)
    ls = layer_sig.copy()
    ls["date"] = pd.to_datetime(ls["date"])
    end = pd.Timestamp(today.date())

    def window(df, a, b):
        return df[(df["date"] > end - pd.Timedelta(days=a)) & (df["date"] <= end - pd.Timedelta(days=b))]

    recent_items = load_recent_items(days=30)
    layers = []
    for L in uni["layers"]:
        d = ls[ls["layer"] == L]
        w7, p7, w30 = window(d, 7, 0), window(d, 14, 7), window(d, 30, 0)
        t7, e7 = int(w7["tight"].sum()), int(w7["ease"].sum())
        tp, ep = int(p7["tight"].sum()), int(p7["ease"].sum())
        heads = [i for i in recent_items if L in i.get("layers", [])]
        heads.sort(key=lambda i: i.get("published") or "", reverse=True)
        layers.append({
            "key": L, "name": names.get(L, L),
            "items7": int(w7["items"].sum()), "tight7": t7, "ease7": e7, "friction7": int(w7["friction"].sum()),
            "net7": t7 - e7, "net_prev7": tp - ep, "trend": (t7 - e7) - (tp - ep),
            "tight30": int(w30["tight"].sum()), "ease30": int(w30["ease"].sum()),
            "headlines": [{k: i.get(k) for k in ("title", "source", "url", "published", "tight", "ease", "friction")}
                          for i in heads[:6]],
        })
    # weekly heat map, last 10 weeks (weeks start on Monday)
    ls["week"] = ls["date"] - pd.to_timedelta(ls["date"].dt.weekday, unit="D")
    last_week = end - pd.Timedelta(days=end.weekday())
    weeks = [last_week - pd.Timedelta(weeks=k) for k in range(9, -1, -1)]
    heat, counts = {}, {}
    for L in uni["layers"]:
        d = ls[ls["layer"] == L].groupby("week")[["tight", "ease", "items"]].sum()
        heat[L] = [int(d.at[w, "tight"] - d.at[w, "ease"]) if w in d.index else 0 for w in weeks]
        counts[L] = [[int(d.at[w, "tight"]), int(d.at[w, "ease"]), int(d.at[w, "items"])] if w in d.index else [0, 0, 0]
                     for w in weeks]
    # per stock, last 7 days
    ss = stock_sig.copy()
    ss["date"] = pd.to_datetime(ss["date"])
    s7 = ss[ss["date"] > end - pd.Timedelta(days=7)].groupby("ticker")[["items", "tight", "ease", "friction"]].sum()
    stocks = {t: {k: int(v) for k, v in row.items()} for t, row in s7.iterrows()}
    return {"as_of": str(end.date()), "layers": layers, "weeks": [str(w.date()) for w in weeks],
            "heat": heat, "heat_counts": counts, "stocks": stocks}


def load_recent_items(days: int) -> list[dict]:
    out = []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    folder = NEWS / "items"
    if not folder.exists():
        return out
    for f in sorted(folder.glob("*.jsonl")):
        try:
            if datetime.strptime(f.stem, "%Y-%m-%d").date() < cutoff - timedelta(days=3):
                continue
        except ValueError:
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return [i for i in out if (i.get("published") or "")[:10] >= str(cutoff)]


def main() -> int:
    uni, _ = load_config()
    members = layer_members(uni)
    layer_of = {t: L for L, ts in members.items() for t in ts}
    names = uni.get("news_names", {})
    NEWS.mkdir(parents=True, exist_ok=True)
    (NEWS / "items").mkdir(exist_ok=True)
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)

    seen_path = NEWS / "seen.json"
    seen: dict[str, str] = json.loads(seen_path.read_text()) if seen_path.exists() else {}
    first_run = not (NEWS / "layer_signals.csv").exists()
    days = 30 if first_run else 3
    print(f"news radar: {'backfill 30 days' if first_run else 'last 3 days'}")

    queries = [("stock", t, f'"{names.get(t, t)}" {SUPPLY_TERMS}', [layer_of[t]]) for t in layer_of]
    queries += [("theme", th["q"], th["q"], [th["layer"]]) for th in uni.get("news_themes", [])]

    found: dict[str, dict] = {}
    ok = {"google": 0, "yahoo": 0}
    fail = {"google": 0, "yahoo": 0}
    for kind, key, q, layers in queries:
        batches = []
        g = google_news(q, days)
        (ok if g is not None else fail)["google"] += 1
        batches.append(g or [])
        if kind == "stock" and not key.endswith(".KS"):
            y = yahoo_news(key)
            (ok if y is not None else fail)["yahoo"] += 1
            batches.append(y or [])
        for item in (x for b in batches for x in b):
            if not item["title"] or item["published"] is None:
                continue
            if item["published"] < now - timedelta(days=days + 1):
                continue
            iid = item_id(item["title"])
            rec = found.setdefault(iid, {**item, "id": iid, "tickers": set(), "themes": set(), "layers": set()})
            (rec["tickers"] if kind == "stock" else rec["themes"]).add(key)
            rec["layers"].update(layers)
        time.sleep(1.0)

    new = [r for iid, r in found.items() if iid not in seen]
    print(f"  google ok {ok['google']}/{ok['google'] + fail['google']}, yahoo ok {ok['yahoo']}/{ok['yahoo'] + fail['yahoo']}; "
          f"{len(found)} headlines, {len(new)} new")

    layer_rows, stock_rows, by_day = [], [], {}
    for r in new:
        sc = score(f"{r['title']}. {r.get('text', '')}")
        day = r["published"].date().isoformat()
        for L in r["layers"]:
            layer_rows.append({"date": day, "layer": L, "items": 1, **{k: sc[k] for k in ("tight", "ease", "friction")}})
        for t in r["tickers"]:
            stock_rows.append({"date": day, "ticker": t, "items": 1, **{k: sc[k] for k in ("tight", "ease", "friction")}})
        if sc["tight"] or sc["ease"] or sc["friction"]:
            by_day.setdefault(now.date().isoformat(), []).append({
                "id": r["id"], "title": r["title"], "source": r["source"], "url": r["url"],
                "published": r["published"].isoformat(timespec="minutes"), "layers": sorted(r["layers"]),
                "tickers": sorted(r["tickers"]), "themes": sorted(r["themes"]), **sc})
        seen[r["id"]] = now.date().isoformat()

    cols_l, cols_s = ["date", "layer", "items", "tight", "ease", "friction"], ["date", "ticker", "items", "tight", "ease", "friction"]
    layer_sig = upsert(NEWS / "layer_signals.csv", pd.DataFrame(layer_rows, columns=cols_l), ["date", "layer"])
    stock_sig = upsert(NEWS / "stock_signals.csv", pd.DataFrame(stock_rows, columns=cols_s), ["date", "ticker"])
    for day, rows in by_day.items():
        with (NEWS / "items" / f"{day}.jsonl").open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    keep_after = (now - timedelta(days=14)).date().isoformat()
    seen = {k: v for k, v in seen.items() if v >= keep_after}
    seen_path.write_text(json.dumps(seen), encoding="utf-8")

    radar = build_radar(uni, layer_sig, stock_sig, now)
    radar["generated_utc"] = now.isoformat(timespec="seconds")
    radar["sources_ok"] = ok
    radar["sources_failed"] = fail
    (DOCS_DATA / "radar.json").write_text(json.dumps(radar, ensure_ascii=False, indent=1), encoding="utf-8")
    top = sorted(radar["layers"], key=lambda x: -x["net7"])[:3]
    print("  top news pressure: " + ", ".join(f"{x['name']} {x['net7']:+d}" for x in top))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # the radar must never block prices and scores
        print(f"news radar crashed: {e}", file=sys.stderr)
        sys.exit(0)
