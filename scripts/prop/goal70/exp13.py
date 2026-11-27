from sim import *
Dd = D.copy(); below50 = Dd.c.shift(1) < Dd.c.rolling(50).mean().shift(1)
res = []
for cap in (1.0, 1.5, 2.0):
    b = build("b12_14", cap=cap)
    for m in (1.0, 1.25, 1.5):
        days = build_mult(b, {d: (m if v else 1.0) for d, v in below50.items()})
        for X in (6, 8, 10, 12):
            o, _ = evaluate(days, fixed(X), target_stop=True)
            res.append(dict(cap=cap, m=m, X=X, A=o["A"]["p12"], B=o["B"]["p12"], all=o["all"]["p12"], A24=o["A"]["p24"], B24=o["B"]["p24"]))
R = pd.DataFrame(res)
bestB = R.loc[R.B.idxmax()]; bestA = R.loc[R.A.idxmax()]
print("picked on B (2022-26):", dict(bestB[["cap", "m", "X"]]), "-> B", bestB.B, "| out-of-sample A:", bestA.A if False else bestB.A)
print("picked on A (2016-21):", dict(bestA[["cap", "m", "X"]]), "-> A", bestA.A, "| out-of-sample B:", bestA.B)
print("cross-validated estimate (avg of out-of-sample halves):", round((bestB.A + bestA.B) / 2, 1))
print(R.sort_values("all", ascending=False).head(8).to_string())
