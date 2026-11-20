"""Real MQL5 code (harness trades) vs ea_port.replay (Python port that matches the research backtest)."""
import sys, datetime as dt, collections
import pandas as pd
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import ea_port
K = 41.0
tr = pd.read_csv(sys.argv[1])
def ny(t): return dt.datetime(1970, 1, 1) + dt.timedelta(seconds=int(t) - 7 * 3600)
tr["en"] = tr.entry_srv.map(ny); tr["ex"] = tr.exit_srv.map(ny)
tr["date"] = tr.en.map(lambda x: x.date())
tr["et"] = tr.en.map(lambda x: x.hour * 60 + x.minute)
tr["xt"] = tr.ex.map(lambda x: min(959, x.hour * 60 + x.minute) if x.date() == x.date() else 959)
ses = ea_port.load_sessions()
rp = ea_port.replay(ses, start=dt.date(2016, 4, 1), end=dt.date(2026, 11, 19))
ea_days = {d: g for d, g in tr.groupby("date")}
mism = []; usd_ea = 0; usd_py = 0; n_py = 0
for _, r in rp.iterrows():
    d = r.date
    py = sorted((t["side"], t["et"], min(959, t["xt"])) for t in r.trades)
    g = ea_days.get(d)
    ea = sorted((int(x.side), int(x.et), int(x.xt)) for _, x in g.iterrows()) if g is not None else []
    pe = float(g.profit.sum()) if g is not None else 0.0
    usd_ea += pe; usd_py += r.usd; n_py += len(py)
    if py != ea:
        mism.append((d, py, ea, round(r.usd), round(pe), r.blocked))
extra = set(ea_days) - set(rp.date)
print("days", len(rp), "trades py", n_py, "ea", len(tr), "| mismatched days", len(mism), "| EA trade days not in replay", sorted(extra)[:10])
print("total $ py %.0f  ea %.0f  ratio %.5f" % (usd_py, usd_ea, usd_ea / usd_py))
for m in mism[:20]:
    print(m)
