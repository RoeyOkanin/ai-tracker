"""Re-simulate with no NEW entries at given bar-end times (exits still checked). Daily P&L, cost 5, $12, + skip-after-win."""
import numpy as np, pandas as pd
import strategies as S
q = S.load("../../data/prop/QQQ_5m.csv.gz")
D = q.groupby("date").agg(o=("open", "first"), c=("close", "last"))
vol = D.c.pct_change().rolling(14).std().shift(1)
base_src = open("strategies.py").read()
def run(block):
    src = base_src.replace("if not pos and on_half and bar_end.time()", f"if not pos and on_half and bar_end.strftime('%H:%M') not in {block!r} and bar_end.time()")
    assert src != base_src
    ns = {}; exec(compile(src, "s", "exec"), ns)
    tr = ns["noise_momentum"](q)
    out = {}
    for d, ts in tr.items():
        s = vol.get(d)
        if s is None or not np.isfinite(s): continue
        vs = min(2, 0.012 / s); f = 25000 / (D.o[d] * 41) * vs
        out[d] = sum((t["pnl_pts"] * f - 5 * vs) * 12 for t in ts)
    p = pd.Series(out).sort_index()
    sk = p.where(~(p.shift(1) > 2000), 0)   # skip after win
    return p, sk
for block in ([], ["12:00"], ["12:00", "14:00"]):
    p, sk = run(block)
    idx = pd.to_datetime(p.index)
    def st(x, a, b):
        x = x[(idx >= a) & (idx < b)]; e = x.cumsum()
        return f"{x.sum():9,.0f} sh {x.mean()/x.std()*np.sqrt(252):4.2f} dd {(e-e.cummax()).min():8,.0f}"
    print(f"block {block}: 2016-21 {st(sk,'2016','2022')} | 2022-26 {st(sk,'2022','2027')} | last5y {st(sk,'2021-11-14','2027')}", flush=True)
