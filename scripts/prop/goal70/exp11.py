from sim import *
Dd = D.copy(); below50 = Dd.c.shift(1) < Dd.c.rolling(50).mean().shift(1)
cfg = {"old (cap2, no tilt)": build("b12_14", cap=2.0),
       "new (cap1, x1.5<MA50)": build_mult(build("b12_14", cap=1.0), {d: (1.5 if v else 1.0) for d, v in below50.items()})}
for name, days in cfg.items():
    for X in (6, 8, 10):
        r = [funded(days, s, X) for s in range(0, len(days) - 252, 3)]
        p = np.array([x[0] for x in r]); idx = pd.to_datetime([days[s][0] for s in range(0, len(days) - 252, 3)])
        A_ = idx < "2022-01-01"
        print(f"{name:24s} funded ${X}: avg ${p.mean():,.0f}/yr (A ${p[A_].mean():,.0f}, B ${p[~A_].mean():,.0f}) median ${np.median(p):,.0f} breach {100*np.mean([x[1]=='breach' for x in r]):.0f}%", flush=True)
