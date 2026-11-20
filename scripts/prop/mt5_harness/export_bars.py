"""Export QQQ 5-min bars (x41 = US100 level) with FTMO server timestamps (server = NY wall clock + 7h).

variant research : every bar as in the research data (early-close days keep their post-market bars)
variant cfd      : like the US100.cash CFD: early-close days stop at 13:15 NY; optional synthetic
                   futures-only holiday mornings (04:00-13:00 NY) copied from a template day:
                   hol=YYYY-MM-DD:TEMPLATE-YYYY-MM-DD (repeatable)
"""
import sys, datetime as dt
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from nyse_cal import early_closes

QQQ = HERE.parents[2] / "data/prop/QQQ_5m.csv.gz"
K = 41.0
variant, out = sys.argv[1], sys.argv[2]
hols = [a.split("=", 1)[1] for a in sys.argv[3:] if a.startswith("hol=")]

df = pd.read_csv(QQQ)
ts = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
df["nyw"] = ts
df = df.sort_values("nyw").drop_duplicates("nyw")
df["date"] = df.nyw.dt.date
mins = df.nyw.dt.hour * 60 + df.nyw.dt.minute

if variant == "cfd":
    ec = set()
    for y in range(2015, 2028):
        ec |= early_closes(y)
    k = df.nyw.dt.year * 10000 + df.nyw.dt.month * 100 + df.nyw.dt.day
    drop = k.isin(ec) & (mins >= 13 * 60 + 15)
    print("early-close bars dropped:", int(drop.sum()), "on", int(k[drop].nunique()), "days")
    df = df[~drop]
    add = []
    for h in hols:
        hd, td = [dt.date.fromisoformat(x) for x in h.split(":")]
        tmpl = df[(df.date == td)].copy()
        tmpl = tmpl[(tmpl.nyw.dt.hour * 60 + tmpl.nyw.dt.minute) < 13 * 60]
        prev = df[df.nyw < pd.Timestamp(hd)].iloc[-1]
        f = prev.close / tmpl.open.iloc[0]
        for c in ("open", "high", "low", "close", "vwap"):
            tmpl[c] = tmpl[c] * f
        tmpl["volume"] = (tmpl.volume * 0.3).round().clip(lower=1)
        tmpl["nyw"] = tmpl.nyw.apply(lambda t: dt.datetime.combine(hd, t.time()))
        tmpl["date"] = hd
        add.append(tmpl)
        print("synthetic holiday session", hd, "from", td, len(tmpl), "bars, scale", round(f, 4))
    if add:
        df = pd.concat([df] + add).sort_values("nyw")

srv = (df.nyw - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1) + 7 * 3600
o = pd.DataFrame(dict(t=srv.values, o=(df.open * K).round(2).values, h=(df.high * K).round(2).values,
                      l=(df.low * K).round(2).values, c=(df.close * K).round(2).values,
                      v=df.volume.clip(lower=1).round().astype(np.int64).values))
o.to_csv(out, index=False, header=False)
print(out, len(o), "bars")
