from sim import *
oth = pickle.load(open(SP + "g70_other.pkl", "rb"))
base = build("b12_14", cap=1.0)
nq = pd.Series({d: sum(t[0] for t in trs) / 25000.0 for d, trs in base})   # % of notional per unit
df = pd.DataFrame(dict(NQ=nq, **oth)).dropna()
idx = pd.to_datetime(df.index)
for era, (a, b) in {"A": ("2016", "2022"), "B": ("2022", "2027")}.items():
    x = df[(idx >= a) & (idx < b)]
    sh = (x.mean() / x.std() * np.sqrt(252)).round(2).to_dict()
    print(era, "sharpe", sh, "corr with NQ", x.corr()["NQ"].round(2).to_dict())
    for sym in ("SPY", "DIA", "IWM", "GLD"):
        for w in (0.25, 0.5):
            c = x.NQ + w * x[sym] * x.NQ.std() / x[sym].std()
            print(f"   NQ + {w} x {sym} (risk-matched): sharpe {c.mean()/c.std()*np.sqrt(252):.2f}")
