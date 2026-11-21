from instant_sim import *
import itertools
FEE = 2999 * 1.15
def run(**kw):
    R = [life(F.days, s, **kw) for s in starts]
    lt = np.array([r[0] if r[0] else 10**9 for r in R]); paid = np.array([r[1] for r in R])
    y1 = np.array([life(F.days, s, horizon=YEAR, **kw)[1] for s in starts])
    return 100*np.mean(lt <= YEAR), 100*np.mean(lt < 10**9), paid.mean(), y1.mean()
for cons in (0.30, 0.50):
  print("cons", cons)
  for keep, capd, X in itertools.product([2000, 3000, 5000], [None, 1000, 1500, 2000], [4, 6, 8, 10]):
    d1, d3, pa, y1 = run(X=X, lock=False, keep=keep, cap=capd, cons=cons)
    print(f"X{X:3d} keep {keep:5d} daycap {str(capd):5s} | dead1y {d1:5.1f}% dead3y {d3:5.1f}% | yr1 ${y1:7,.0f} 3y ${pa:7,.0f} net3y ${pa-FEE:7,.0f}", flush=True)
