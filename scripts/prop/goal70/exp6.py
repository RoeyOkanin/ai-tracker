from sim import *
days = build("b12_14", cap=1.0)
rows = []
for d, trs in days:
    rows.append(dict(d=d, pnl=10 * sum(t[0] for t in trs), L=10 * sum(t[0] for t in trs if t[4] > 0), S=10 * sum(t[0] for t in trs if t[4] < 0), n=len(trs)))
T = pd.DataFrame(rows).set_index("d")
Dd = D.copy()
Dd["ma200"] = Dd.c.rolling(200).mean().shift(1); Dd["above"] = (Dd.c.shift(1) > Dd.ma200)
Dd["ma50"] = Dd.c.rolling(50).mean().shift(1); Dd["above50"] = (Dd.c.shift(1) > Dd.ma50)
Dd["rv60"] = Dd.ret.rolling(60).std().shift(1); Dd["rv250med"] = Dd.rv60.rolling(250).median()
Dd["calm"] = Dd.rv60 < Dd.rv250med
T = T.join(Dd[["above", "above50", "calm", "vol14"]])
T["era"] = np.where(pd.to_datetime(T.index) < "2022-01-01", "A", "B")
T["eq20"] = T.pnl.rolling(20).sum().shift(1); T["eq60"] = T.pnl.rolling(60).sum().shift(1); T["eq120"] = T.pnl.rolling(120).sum().shift(1)
def show(col):
    print(f"-- by {col}: mean daily $ (n days)   total L / S")
    for era in ("A", "B"):
        x = T[T.era == era]
        g = x.groupby(col)
        print("  ", era, " ".join(f"{k}: {v.pnl.mean():6.1f} ({len(v)}) L {v.L.sum()/1000:5.0f}k S {v.S.sum()/1000:5.0f}k" for k, v in g))
for c in ("above", "above50", "calm"):
    show(c)
for c in ("eq20", "eq60", "eq120"):
    T[c + "_pos"] = T[c] > 0
    show(c + "_pos")
