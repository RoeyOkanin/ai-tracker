from sim import *
Rg = regime_series()
base = build("b12_14", cap=1.0)
def daily_stats(days, X=10):
    s = pd.Series({d: X * sum(t[0] for t in trs) for d, trs in days}); idx = pd.to_datetime(s.index); res = []
    for a, b in (("2016", "2022"), ("2022", "2027")):
        x = s[(idx >= a) & (idx < b)]; e = x.cumsum()
        res.append(f"{x.sum()/1000:5.0f}k sh {x.mean()/x.std()*np.sqrt(252):4.2f} dd {(e-e.cummax()).min()/1000:4.0f}k")
    return " | ".join(res)
def row(days, sz, **kw):
    o, _ = evaluate(days, sz, **kw)
    return f"{o['all']['p12']:5.1f}/{o['all']['p24']:5.1f} A {o['A']['p12']:5.1f}/{o['A']['p24']:5.1f} B {o['B']['p12']:5.1f}/{o['B']['p24']:5.1f} med {o['all']['med']}"
V = {"none": base}
for n in (50, 200):
    b = Rg[f"below{n}"]
    V[f"x1.5 below MA{n}"] = build_mult(base, {d: (1.5 if v else 1.0) for d, v in b.items()})
    V[f"x0.6 above MA{n}"] = build_mult(base, {d: (1.0 if v else 0.6) for d, v in b.items()})
for k, days in V.items():
    print(f"{k:18s} {daily_stats(days)}", flush=True)
    for X in (8, 10, 12):
        print(f"    ${X} +tgt:", row(days, fixed(X), target_stop=True), flush=True)
