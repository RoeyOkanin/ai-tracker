"""Withdrawal rules vs edge decay: burn rate within 3 years, lowest equity (closest call to the 90.5k guard), $/yr to the trader."""
import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    import funded_life as F
import numpy as np
A, YEAR = F.A, F.YEAR
decks = {e: (F.days if e == 0 else F.make_days(5.0 + e)) for e in (0, 2, 4)}
for name, trig, keep in F.rules:
    row = []
    for e, dd in decks.items():
        lt, paid, low, yrs = F.run(dd, trig, keep)
        row.append(f"edge-{ {0:'0%',2:'19%',4:'38%'}[e] }: burn3y {100*np.mean(lt<10**9):4.1f}% low worst ${A+low.min():,.0f} p5 ${A+np.percentile(low,5):,.0f} med ${A+np.median(low):,.0f} $/yr {paid.sum()/yrs.sum():,.0f}")
    print(f"{name}\n   " + "\n   ".join(row), flush=True)
# where does the worst base-case low happen?
worst = None
for s in F.starts:
    F.life(s, trigger=5000, keep=0)
    if worst is None or F.LOW < worst[0]:
        worst = (F.LOW, s)
print("worst base start:", F.days[worst[1]][0], "low", A + worst[0])
