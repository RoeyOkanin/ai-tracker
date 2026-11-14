from sim import *
def row(days, sz, **kw):
    o, _ = evaluate(days, sz, **kw)
    return f"{o['all']['p12']:5.1f}/{o['all']['p24']:5.1f} A {o['A']['p12']:5.1f}/{o['A']['p24']:5.1f} B {o['B']['p12']:5.1f}/{o['B']['p24']:5.1f} med {o['all']['med']}"
for cap in (1.0, 1.5, 2.0):
    days = build("b12_14", cap=cap)
    print(f"=== cap {cap}", flush=True)
    for X in (8, 10, 12, 14):
        print(f" fixed ${X}            ", row(days, fixed(X)), flush=True)
        print(f" fixed ${X} +tgtstop   ", row(days, fixed(X), target_stop=True), flush=True)
        for p, lo, hi in ((1, 0.25, 1.0), (2, 0.25, 1.0), (1, 0.25, 1.5), (1, 0.5, 1.5), (0.5, 0.25, 1.0)):
            print(f" cushion ${X} p{p} lo{lo} hi{hi} +tgt", row(days, cushion(X, p=p, lo=lo, hi=hi), target_stop=True), flush=True)
