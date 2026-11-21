from sim import *
Dd = D.copy()
base = build("b12_14", cap=1.0)
def row(days, sz, **kw):
    o, _ = evaluate(days, sz, **kw)
    return f"{o['all']['p12']:5.1f}/{o['all']['p24']:5.1f} A {o['A']['p12']:5.1f}/{o['A']['p24']:5.1f} B {o['B']['p12']:5.1f}/{o['B']['p24']:5.1f} med {o['all']['med']}"
def sh(days):
    s = pd.Series({d: sum(t[0] for t in trs) for d, trs in days}); idx = pd.to_datetime(s.index)
    return " ".join(f"{(lambda x: x.mean()/x.std()*np.sqrt(252))(s[(idx>=a)&(idx<b)]):.2f}" for a, b in (("2016","2022"),("2022","2027")))
print("MA length x multiplier (below MA -> m), $10 + target stop; sharpe A B")
for n in (20, 50, 100, 200):
    below = Dd.c.shift(1) < Dd.c.rolling(n).mean().shift(1)
    for m in (1.25, 1.5, 2.0):
        days = build_mult(base, {d: (m if v else 1.0) for d, v in below.items()})
        print(f" MA{n:3d} x{m}: sh {sh(days)}  $10: {row(days, fixed(10), target_stop=True)}  $8: {row(days, fixed(8), target_stop=True)}", flush=True)
