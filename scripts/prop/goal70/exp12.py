from sim import *
Dd = D.copy(); below50 = Dd.c.shift(1) < Dd.c.rolling(50).mean().shift(1)
days = build_mult(build("b12_14", cap=1.0), {d: (1.5 if v else 1.0) for d, v in below50.items()})
o, df = evaluate(days, fixed(10), step=1, target_stop=True)
df["below50"] = df.d.map(below50)
df["vol14"] = df.d.map(Dd.vol14)
df["volq"] = pd.qcut(df.vol14, 3, labels=["low", "mid", "high"])
for col in ("below50", "volq"):
    for era in ("A", "B"):
        x = df[df.era == era]
        print(col, era, " ".join(f"{k}: pass12 {100*v.p12.mean():.0f}% fail {100*(v.r=='fail').mean():.0f}% n={len(v)}" for k, v in x.groupby(col)))
last = Dd.index[-1]
print("now:", last, "close", round(Dd.c.iloc[-1], 2), "MA50", round(Dd.c.rolling(50).mean().iloc[-1], 2), "vol14", round(Dd.ret.rolling(14).std().iloc[-1], 4),
      "vol tercile cuts", df.vol14.quantile([1/3, 2/3]).round(4).tolist())
