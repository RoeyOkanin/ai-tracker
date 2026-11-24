"""Randomised fault scenarios for the real EA code, checked against invariants (round 5).
usage: python3 fuzz.py VER N [SEED] [OUTDIR]   (run ./build.sh first)
Each scenario is a 10-25 day window with random restarts (with or without a login delay), disconnects,
Algo Trading off, VPS downtime, rejected / partly filled orders, an input change, small volume or margin
limits, near-target and near-floor balances. Flags: runtime error, two positions at once, a position left
open outside the trading window while the terminal is healthy, entries at a wrong time or day, entries
after the equity guard or after the target, FTMO breaches, request storms, positions left at the end,
a size above the day's maximum, a server stop that allows more than the room to FTMO's limits.
Since v2.04 also: trade state that reaches the terminal seconds late (tradelag/ballag), orders executed
although OrderSend reported a failure (ghost) and orders executed seconds after a timeout (late)."""
import sys, random, subprocess, datetime as dt, re, os, json, concurrent.futures as cf
H = os.path.dirname(os.path.abspath(__file__)) + "/build/"
ver, N = sys.argv[1], int(sys.argv[2])
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
out = sys.argv[4] if len(sys.argv) > 4 else H + "fuzz"
os.makedirs(out, exist_ok=True)
R = random.Random(seed)

def rtime(d0, days):
    """random NY instant in the window, biased to decision times, the open, the exit and the FTMO day change"""
    d = d0 + dt.timedelta(days=R.randrange(days))
    k = R.random()
    if k < 0.35:   m = R.choice(range(600, 931, 30)) * 60 + R.randint(-150, 150)          # around a checkpoint
    elif k < 0.50: m = 959 * 60 + R.randint(-300, 400)                                     # around the 15:59 exit
    elif k < 0.60: m = 570 * 60 + R.randint(-400, 1500)                                    # around the open / day preparation
    elif k < 0.67: m = 18 * 3600 + R.randint(-120, 120)                                    # FTMO day change (00:00 Prague, winter)
    elif k < 0.72: m = 13 * 3600 + R.randint(-1800, 1200)                                  # early-close time
    else:          m = R.randint(0, 86399)
    return dt.datetime.combine(d, dt.time()) + dt.timedelta(seconds=m)
f = lambda t: t.strftime("%Y-%m-%dT%H:%M:%S")

def scenario(i):
    special = [(11, 18), (12, 15), (6, 26), (3, 5), (10, 22), (12, 26), (1, 10), (4, 1)]   # holidays, half-days, DST weeks
    y = R.randint(2016, 2026)
    if R.random() < 0.45:
        mo, da = R.choice(special); d0 = dt.date(y, mo, da)
    else:
        d0 = dt.date(y, 1, 1) + dt.timedelta(days=R.randrange(365))
    d0 = max(dt.date(2016, 6, 1), min(dt.date(2026, 10, 20), d0))
    days = R.randint(10, 25)
    a = [f"ver={ver}", "bars=bars_cfd.csv", f"from={d0}", f"to={d0 + dt.timedelta(days=days)}", "tstep=60", "in.InpLogCsv=false",
         f"view={R.choice([1, 1, 1, 1, 0])}"]
    if R.random() < 0.4: a.append("dense=10")
    if R.random() < 0.7: a += ["spread_bp=1.2", "slip_bp=0.8"]
    k = R.random()
    if k < 0.20:   a += ["in.InpTargetPct=0", "in.InpDollarsPerPoint=8", "in.InpBufferScaling=true", f"balance={R.choice([100000, 93000, 91200, 104000])}"]
    elif k < 0.45: a += [f"in.InpTargetPct={R.choice([10, 10, 5])}", f"balance={R.choice([109300, 108000, 104600, 100000])}"]
    elif k < 0.60: a += [f"in.InpTargetPct={R.choice([1.5, 3])}"]
    elif k < 0.70: a += ["in.InpTargetPct=10", f"balance={R.choice([91000, 92500, 95400])}"]
    else:          a += ["in.InpTargetPct=0"]
    if R.random() < 0.08: a.append("volmax=5")
    if R.random() < 0.08: a.append("leverage=3")
    lag = 0
    if R.random() < 0.35:
        lag = R.choice([1, 2, 3, 5, 15]); a.append(f"tradelag={lag}")
        if R.random() < 0.4: a.append(f"ballag={R.choice([1, 3, 10])}")
    ev = []
    sync = R.choice([0, 5, 5, 5, 20, 60])
    if sync: a.append(f"sync={sync}")
    for _ in range(R.choice([0, 0, 1, 2, 3, 5])):
        t = rtime(d0, days); a.append("restart=" + f(t)); ev.append(t)
    for key, n, durs in (("relogin", R.choice([0, 0, 0, 1, 2, 4]), [2, 5, 10, 30, 120]),
                         ("eqzero", R.choice([0, 0, 0, 0, 1, 2]), [1, 3, 10, 60]),
                         ("disconnect", R.choice([0, 0, 1, 2, 4]), [20, 120, 600, 2700, 10800]),
                         ("algooff", R.choice([0, 0, 0, 1, 2]), [20, 120, 600, 2700, 10800]),
                         ("eadead", R.choice([0, 0, 0, 1, 2]), [60, 600, 7200, 72000])):
        for _ in range(n):
            t = rtime(d0, days); a.append(f"{key}={f(t)},{f(t + dt.timedelta(seconds=R.choice(durs)))}"); ev.append(t)
    for _ in range(R.choice([0, 0, 1, 2, 3])):
        t = rtime(d0, days); kind = R.choice(["closes", "closes", "opens", "both", "partial", "ghost", "late", "late"])
        rc = 0 if kind == "partial" else R.choice([10012, 10012, 10031]) if kind in ("ghost", "late") else R.choice([10004, 10006, 10006, 10018, 10021, 10012, 10016, 10019])
        dur = R.choice([30, 120, 600, 2400, 7200, 86400]) if kind in ("ghost", "late") else R.choice([30, 120, 600, 2400])
        a.append(f"fault={kind},{f(t)},{f(t + dt.timedelta(seconds=dur))},{rc}" + (f",{R.choice([2, 8, 15, 30, 45, 90, 400, 1900])}" if kind == "late" else "")); ev.append(t)
    if R.random() < 0.15:
        t = rtime(d0, days); a.append("reinit=" + f(t) + ";" + R.choice(["InpDollarsPerPoint=8", "InpTrendMA=0", "InpDollarsPerPoint=12", "InpSkipAfterWinPts=0"])); ev.append(t)
    if R.random() < 0.10:
        a += ["restart_daily=0929", "hole_daily=0929," + R.choice(["0945", "1010"]) + ",1200"]
    for t in ev:                                   # 1-second timer around every event, like EventSetTimer(1)
        a.append(f"timer1s={f(t - dt.timedelta(seconds=120))},{f(t + dt.timedelta(seconds=900))}")
    return a

def run(i_a):
    r = run1(i_a)
    if ("DAILY_BREACH" in r["flags"] or "MAX_BREACH" in r["flags"]) and "dense=1" not in i_a[1]:
        # 5 ticks per bar jump up to a whole bar range between two ticks: confirm with 1-second ticks
        r2 = run1((i_a[0], [x for x in i_a[1] if not x.startswith("dense=")] + ["dense=1"]))
        for k in ("DAILY_BREACH", "MAX_BREACH"):
            if k in r["flags"] and k not in r2["flags"]:
                r["flags"] = [x for x in r["flags"] if x != k]; r["coarse_tick_breach"] = 1
    return r

def run1(i_a):
    i, a = i_a
    pr = subprocess.run([H + "driver"] + a + ["quiet=1"], capture_output=True, text=True, cwd=H)
    o = pr.stdout
    g = lambda pat, d="-1": (re.search(pat, o) or [None, d])[1]
    r = dict(i=i, rc=pr.returncode, args=" ".join(a),
             maxpos=int(g(r"max_positions=(\d+)")), stuck=int(g(r"stuck_outside_window_s=(\d+)")),
             bad_day=int(g(r"bad_entry_day=(\d+)")), bad_time=int(g(r"bad_entry_time=(\d+)")), bad_noentry=int(g(r"bad_no_entry=(\d+)")),
             after_guard=int(g(r"entry_after_guard=(\d+)")), after_target=int(g(r"entry_after_target=(\d+)")),
             breach=int(g(r"daily_breach_ticks=(\d+)")), maxbreach=int(g(r"max_breach=(\d+)")),
             srv=int(g(r"server=\d+ max/day all=\d+ \(\d+\) server=(\d+)")), openpos=int(g(r"open_positions=(\d+)")),
             bad_volume=int(g(r"bad_volume=(\d+)", "0")), bad_sl=int(g(r"bad_sl=(\d+)", "0")), two_s=int(g(r"two_positions_s=(\d+)", "0")),
             deals=int(g(r"deals=(\d+)")), err=pr.stderr[-300:])
    fl = []
    if r["rc"] != 0 or r["maxpos"] < 0: fl.append("CRASH")
    args = " ".join(a)
    lag = max([int(x.split("=")[1]) for x in a if x.startswith("tradelag=")] + [0])
    late = "fault=late" in args or "fault=ghost" in args
    # v2.04 closes a duplicate as soon as the terminal shows it: two positions may exist for the lag plus the close backoff
    if r["maxpos"] > 1 and (ver < "v204" or r["two_s"] > lag + 20 or r["maxpos"] > 2): fl.append("TWO_POSITIONS")
    if r["bad_volume"] > 0: fl.append("BAD_VOLUME")
    if r["bad_sl"] > 0 and not late: fl.append("BAD_SL")      # a late fill has a price the stop was not computed for
    if r["stuck"] > 300: fl.append("STUCK")
    for k in ("bad_day", "bad_time", "bad_noentry", "after_guard", "after_target"):
        if r[k] > 0 and not (late and k != "bad_day"): fl.append(k.upper())   # a late fill arrives when the server decides
    if r["breach"] > 0: fl.append("DAILY_BREACH")
    if r["maxbreach"] > 0: fl.append("MAX_BREACH")
    if r["srv"] > 60: fl.append("REQUESTS")
    if r["openpos"] > 0: fl.append("OPEN_AT_END")
    r["flags"] = fl
    return r

sc = [(i, scenario(i)) for i in range(N)]
with cf.ThreadPoolExecutor(4) as ex:
    rows = list(ex.map(run, sc))
json.dump(rows, open(f"{out}/fuzz_{ver}_{seed}.json", "w"), indent=0)
from collections import Counter
c = Counter(x for r in rows for x in r["flags"])
print(f"{ver} seed {seed}: {N} scenarios, {sum(r['deals'] for r in rows)} deals, flagged {sum(1 for r in rows if r['flags'])}: {dict(c)}"
      f" | breaches only with 5 ticks per bar (gone with 1-second ticks): {sum(r.get('coarse_tick_breach', 0) for r in rows)}")
for r in rows:
    if r["flags"]:
        print(r["i"], r["flags"], {k: r[k] for k in ("maxpos", "two_s", "stuck", "breach", "maxbreach", "srv", "openpos", "bad_volume", "bad_sl")}, "\n   ", r["args"], r["err"])
