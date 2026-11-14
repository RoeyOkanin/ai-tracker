from sim import *
def row(days, sz, **kw):
    o, _ = evaluate(days, sz, **kw)
    return f"{o['all']['p12']:5.1f}/{o['all']['p24']:5.1f} A {o['A']['p12']:5.1f}/{o['A']['p24']:5.1f} B {o['B']['p12']:5.1f}/{o['B']['p24']:5.1f} med {o['all']['med']}"
days = build("b12_14", cap=1.0)
print("phase-specific sizing, cap 1.0, target stop")
for x1 in (8, 10, 12):
    for x2 in (6, 8, 10, 12, 14):
        print(f" P1 ${x1} P2 ${x2}: ", row(days, fixed(x1, x2), target_stop=True), flush=True)
