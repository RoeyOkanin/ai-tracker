from sim import *
new = build("b12_14")
for X in (8, 12):
    o, df = evaluate(new, fixed(X), step=1)
    df["y"] = pd.to_datetime(df.d).dt.year
    print(f"${X} by start year: pass12 / fail / timeout(24m) / median days")
    print(df.groupby("y").apply(lambda x: f"{100*x.p12.mean():5.1f} {100*(x.r=='fail').mean():5.1f} {100*(x.r=='timeout').mean():5.1f} {x[x.r=='pass'].t.median()}").to_string())
