"""EA NYSE calendar (real EA code, build/cal_check) vs the official XNYS calendar (exchange_calendars), 2016-2035.
usage: python3 cal_check.py      (needs: pip install exchange_calendars)"""
import os, subprocess, io
import pandas as pd, exchange_calendars as xc
here = os.path.dirname(os.path.abspath(__file__))
out = subprocess.run([os.path.join(here, "build", "cal_check")], capture_output=True, text=True, check=True).stdout
ea = pd.read_csv(io.StringIO(out), header=None, names=["key", "dtype", "hol", "early", "full"])
ea["date"] = pd.to_datetime(ea.key.astype(str)).dt.date
sched = xc.get_calendar("XNYS", start="2016-01-01", end="2035-12-31").schedule
sess = {d.date(): c.tz_convert("America/New_York") for d, c in zip(sched.index, sched["close"])}
bad = []
for r in ea.itertuples():
    c = sess.get(r.date)
    exp = 0 if c is None else (2 if (c.hour, c.minute) < (16, 0) else 1)
    if exp != r.dtype:
        bad.append((r.key, r.date.strftime("%a"), "EA", r.dtype, "XNYS", exp))
print("days", len(ea), "mismatches", len(bad), "(0 = no trading, 1 = regular, 2 = early close)")
for b in bad:
    print(" ", b)
print("early closes XNYS", sum((c.hour, c.minute) < (16, 0) for c in sess.values()), "EA", int((ea.dtype == 2).sum()))
