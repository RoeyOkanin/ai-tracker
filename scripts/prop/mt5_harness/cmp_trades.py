"""Compare two trade files from the driver day by day: same side, entry time, exit time and volume.
usage: python3 cmp_trades.py A.csv B.csv [N days to show]"""
import sys, pandas as pd
a = pd.read_csv(sys.argv[1]); b = pd.read_csv(sys.argv[2]); show = int(sys.argv[3]) if len(sys.argv) > 3 else 8
for x in (a, b): x["day"] = pd.to_datetime(x.entry_srv - 7*3600, unit="s").dt.date
ka = a.groupby("day").apply(lambda g: tuple(zip(g.side, g.entry_srv, g.exit_srv, g.vol.round(2))), include_groups=False)
kb = b.groupby("day").apply(lambda g: tuple(zip(g.side, g.entry_srv, g.exit_srv, g.vol.round(2))), include_groups=False)
days = sorted(set(ka.index) | set(kb.index))
diff = [d for d in days if ka.get(d) != kb.get(d)]
pa = a.groupby("day").profit.sum(); pb = b.groupby("day").profit.sum()
print("trades %d vs %d | trading days %d | days with different trades: %d | P&L %.0f vs %.0f (diff %+.0f)" % (len(a), len(b), len(days), len(diff), a.profit.sum(), b.profit.sum(), b.profit.sum() - a.profit.sum()))
f = lambda k: k and [(s, pd.to_datetime(e-7*3600, unit='s').strftime('%H:%M'), pd.to_datetime(x-7*3600, unit='s').strftime('%H:%M') if x > 0 else 'OPEN', v) for s, e, x, v in k]
for d in diff[:show]:
    print(" ", d, "A", f(ka.get(d)), "%.0f" % pa.get(d, 0), "| B", f(kb.get(d)), "%.0f" % pb.get(d, 0))
