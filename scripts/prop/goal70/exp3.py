from sim import *
def daily_stats(days, X=12):
    s = pd.Series({d: X * sum(t[0] for t in trs) for d, trs in days})
    idx = pd.to_datetime(s.index)
    res = []
    for a, b in (("2016", "2022"), ("2022", "2027")):
        x = s[(idx >= a) & (idx < b)]; e = x.cumsum()
        res.append(f"{x.sum()/1000:6.0f}k sh {x.mean()/x.std()*np.sqrt(252):4.2f} dd {(e-e.cummax()).min()/1000:5.0f}k")
    return " | ".join(res)
def frontier(days, xs=(6, 7, 8, 9, 10, 12), **kw):
    out = []
    for X in xs:
        o, _ = evaluate(days, fixed(X), **kw)
        out.append(f"${X}: {o['all']['p12']:4.1f}/{o['all']['p24']:4.1f} (A {o['A']['p12']:4.1f} B {o['B']['p12']:4.1f}) med {o['all']['med']}")
    return "  ".join(out)
variants = {
    "current (cap2)": build("b12_14"),
    "cap 1.5": build("b12_14", cap=1.5),
    "cap 1.0": build("b12_14", cap=1.0),
    "max entries 1": build("b12_14", max_entries=1),
    "max entries 2": build("b12_14", max_entries=2),
    "max entries 3": build("b12_14", max_entries=3),
}
for name, days in variants.items():
    print(f"{name:16s} daily (no skip) {daily_stats(days)}", flush=True)
    print("   frontier 12m/24m:", frontier(days), flush=True)
