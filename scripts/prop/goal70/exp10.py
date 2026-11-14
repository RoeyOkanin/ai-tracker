from sim import *
Dd = D.copy()
below50 = Dd.c.shift(1) < Dd.c.rolling(50).mean().shift(1)
def row(days, sz, **kw):
    o, df = evaluate(days, sz, **kw)
    return f"{o['all']['p12']:5.1f}/{o['all']['p24']:5.1f} A {o['A']['p12']:5.1f}/{o['A']['p24']:5.1f} B {o['B']['p12']:5.1f}/{o['B']['p24']:5.1f} med {o['all']['med']}", df
cfgs = {"current EA ($12, cap2, no tilt, no tgt)": (2.0, 1.0, 12, False),
        "Balanced: cap1, x1.5<MA50, $10, tgt": (1.0, 1.5, 10, True),
        "Safe: cap1, x1.25<MA50, $8, tgt": (1.0, 1.25, 8, True),
        "Mid: cap1, x1.25<MA50, $9, tgt": (1.0, 1.25, 9, True)}
for cost in (5.0, 6.0, 7.0):
    print(f"=== cost {cost} pts/trade", flush=True)
    for name, (cap, m, X, tgt) in cfgs.items():
        days = build_mult(build("b12_14", cap=cap, cost=cost), {d: (m if v else 1.0) for d, v in below50.items()})
        r, df = row(days, fixed(X), target_stop=tgt)
        print(f" {name:42s} {r}", flush=True)
        if cost == 5.0 and name.startswith(("Bal", "Safe", "Mid")):
            o, df1 = evaluate(days, fixed(X), step=1, target_stop=tgt)
            df1["y"] = pd.to_datetime(df1.d).dt.year
            print("    by start year (pass12 / fail):", " ".join(f"{y}:{100*x.p12.mean():.0f}/{100*(x.r=='fail').mean():.0f}" for y, x in df1.groupby("y")))
