"""Challenge Monte Carlo with the REAL EA code: monthly starts, phase 1 (10%) then phase 2 (5%), FTMO limits, costs."""
import subprocess, sys, datetime as dt, re, concurrent.futures as cf, json
H = __import__("os").path.dirname(__import__("os").path.abspath(__file__)) + "/build/"
ver = sys.argv[1]
bars = next((a for a in sys.argv[2:] if a.endswith(".csv")), "bars_cfd.csv")
extra = [a for a in sys.argv[2:] if not a.endswith(".csv")]
END = dt.date(2026, 11, 19)
def run(start, pct, days=365):
    to = min(END, start + dt.timedelta(days=days))
    cmd = [H + "driver", f"ver={ver}", f"bars={H}{bars}", f"from={start}", f"to={to}", "tstep=60", "quiet=1", "spread_bp=1.2", "slip_bp=0.8",
           "stop_on_ftmo=1", f"in.InpTargetPct={pct}", "in.InpLogCsv=false"] + extra
    pr = subprocess.run(cmd, capture_output=True, text=True)
    out = pr.stdout
    m = re.search(r"RESULT (\S+) (\S+ \S+|-) balance=([\d.]+) days=(\d+)", out)
    if not m:
        print("DRIVER ERROR", start, pct, "rc", pr.returncode, pr.stderr[-500:], out[-500:], " ".join(cmd), flush=True)
        return dict(res="ERROR", date=None, bal=0, full_window=False, maxreq=0)
    req = re.search(r"max/day all=(\d+)", out)
    res, when = m.group(1), m.group(2)
    d = dt.datetime.strptime(when, "%Y.%m.%d %H:%M").date() if when != "-" else None
    full = (to - start).days >= days
    return dict(res=res, date=d, bal=float(m.group(3)), full_window=full, maxreq=int(req.group(1)))
def one(start):
    p1 = run(start, 10)
    r = dict(start=str(start), p1=p1["res"], p1_date=str(p1["date"]), p1_full=p1["full_window"], maxreq=p1["maxreq"])
    if p1["res"] == "PASS":
        s2 = p1["date"] + dt.timedelta(days=1)
        p2 = run(s2, 5)
        r.update(p2=p2["res"], p2_date=str(p2["date"]), p2_full=p2["full_window"], maxreq=max(r["maxreq"], p2["maxreq"]))
    return r
starts = []
for y in range(2016, 2026):
    for mo in range(1, 13):
        d = dt.date(y, mo, 1)
        if d < dt.date(2016, 4, 1) or d > dt.date(2025, 11, 1): continue
        while d.weekday() >= 5: d += dt.timedelta(days=1)
        starts.append(d)
with cf.ThreadPoolExecutor(4) as ex:
    rows = list(ex.map(one, starts))
json.dump(rows, open(H + f"mc_{ver}{'_'+'_'.join(x.split('=')[0].replace('in.','') for x in extra) if extra else ''}.json", "w"), indent=0)
n = len(rows)
p1 = sum(r["p1"] == "PASS" for r in rows)
both = [r for r in rows if r.get("p2") == "PASS"]
def months(a, b): return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days / 30.44
both12 = [r for r in both if months(r["start"], r["p2_date"]) <= 12]
fails = [r for r in rows if r["p1"].startswith("FAIL") or r.get("p2", "").startswith("FAIL")]
to = [r for r in rows if r["p1"] == "TIMEOUT" or r.get("p2") == "TIMEOUT"]
print(f"{ver}: starts {n} | P1 pass {p1} ({p1/n:.0%}) | both phases {len(both)} ({len(both)/n:.0%}) | both within 12m {len(both12)} ({len(both12)/n:.0%}) | failed {len(fails)} | timeout {len(to)} | max requests/day {max(r['maxreq'] for r in rows)}")
import statistics
if both: print("median months to pass both:", round(statistics.median(months(r['start'], r['p2_date']) for r in both), 1))
print("fails:", [(r["start"], r["p1"], r.get("p2")) for r in fails])
