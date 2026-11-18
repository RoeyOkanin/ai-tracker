"""Grow to 4 FTMO 100K 2-Step Swing accounts funded from withdrawals (EA v2: challenge $10 + target stop,
funded $8 + buffer scaling, withdraw everything when balance >= 105K, 80% split, fee refunded with first payout).
All accounts trade the same EA on the same days (fully correlated). Historical paths 2016-2026, 4.1 years each."""
import sys, contextlib, io, numpy as np
sys.path.insert(0, "../goal70")
with contextlib.redirect_stdout(io.StringIO()):
    import funded_life as F
A, FEE = 100_000.0, 620.0          # EUR 540 ~ $620
H = 1028                            # Dec 2026 .. Dec 2030 in trading days


class Acct:
    def __init__(s, k0):
        s.st, s.bal, s.traded, s.prev, s.locked, s.wait, s.fd, s.refund = "p1", 0.0, 0, None, False, 0, 0, True
        s.bought = k0

    def step(s, trs):
        """advance one day; returns cash paid to the trader today"""
        if s.st == "dead":
            return 0.0
        if s.wait:                        # FTMO verification / account issuing
            s.wait -= 1; return 0.0
        if s.st in ("p1", "p2"):
            tgt = (0.10 if s.st == "p1" else 0.05) * A
            if s.locked:
                s.traded += 1
            else:
                X = 10.0
                if s.prev is not None and s.prev > 167 * X:
                    s.prev = 0.0; return 0.0
                cur, anyt = 0.0, False
                lf = -0.095 * A - s.bal; lim = max(-0.045 * A, lf)
                for (pu, mu, fu, et, side) in trs:
                    anyt = True
                    if cur + X * mu <= lim:
                        cur = lim
                        if lim == lf:
                            s.st = "dead"; return 0.0
                        break
                    if s.bal + cur + X * fu >= tgt:
                        cur = tgt - s.bal; s.locked = True; break
                    cur += X * pu
                s.bal += cur; s.traded += anyt; s.prev = cur
                if s.bal >= tgt:
                    s.locked = True
            if s.locked and s.traded >= 4 and s.bal >= tgt:
                s.st = "p2" if s.st == "p1" else "funded"
                s.bal, s.traded, s.prev, s.locked, s.wait, s.fd = 0.0, 0, None, False, 3, 0
            return 0.0
        # funded
        sc = min(1.0, max(0.25, (s.bal + 0.10 * A) / (0.10 * A))); x = 8.0 * sc
        s.fd += 1
        if not (s.prev is not None and s.prev > 167 * x):
            cur = 0.0; lf = -0.095 * A - s.bal; lim = max(-0.045 * A, lf)
            for (pu, mu, fu, et, side) in trs:
                if cur + x * mu <= lim:
                    cur = lim
                    if lim == lf:
                        s.st = "dead"; return 0.0
                    break
                cur += x * pu
            s.bal += cur; s.prev = cur
        else:
            s.prev = 0.0
        if s.fd >= 10 and s.fd % 10 == 0 and s.bal >= 5000:
            pay = 0.8 * s.bal + (FEE if s.refund else 0.0); s.refund = False; s.bal = 0.0
            return pay
        return 0.0


def run(days, start, cushion=1000.0, target=4, buy_all=False):
    cash, pocket, accts, buys, funded_at, burns, fails = 0.0, 0.0, [], [], {}, 0, 0
    n0 = target if buy_all else 1
    for _ in range(n0):
        accts.append(Acct(0)); pocket += FEE; buys.append(0)
    for i in range(H):
        d, trs = days[start + i]
        for a in accts:
            was = a.st
            cash += a.step(trs)
            if a.st == "dead":
                if was == "funded": burns += 1
                elif was in ("p1", "p2"): fails += 1
            if a.st == "funded" and id(a) not in funded_at:
                funded_at[id(a)] = i
        accts = [a for a in accts if a.st != "dead"]
        while len(accts) < target:
            if cash >= FEE + cushion:
                cash -= FEE
            elif not accts:
                pocket += FEE                      # nothing alive: pay a new challenge out of pocket
            else:
                break
            accts.append(Acct(i)); buys.append(i)
    nf = sum(a.st == "funded" for a in accts)
    f4 = sorted(funded_at.values())
    return dict(cash=cash, pocket=pocket, net=cash - pocket, nfunded=nf, buys=buys, burns=burns, fails=fails,
                t4=(f4[3] if len(f4) >= 4 else None), tf=f4)


def summary(days, label, **kw):
    starts = list(range(0, len(days) - H, 5))
    R = [run(days, s, **kw) for s in starts]
    net = np.array([r["net"] for r in R]); pk = np.array([r["pocket"] for r in R])
    nf = np.array([r["nfunded"] for r in R]); t4 = np.array([r["t4"] if r["t4"] is not None else 10**6 for r in R])
    ftimes = [np.median([r["tf"][j] for r in R if len(r["tf"]) > j]) / 21 if any(len(r["tf"]) > j for r in R) else None for j in range(4)]
    btimes = [np.median([r["buys"][j] for r in R if len(r["buys"]) > j]) / 21 for j in range(4)]
    print(f"{label:38s} net to Roey by end-2030: p10 ${np.percentile(net,10):,.0f} median ${np.median(net):,.0f} p90 ${np.percentile(net,90):,.0f} | "
          f"out of pocket median ${np.median(pk):,.0f} max ${pk.max():,.0f} | 4 funded reached {100*np.mean(t4<10**6):.0f}% (median {np.median(t4[t4<10**6])/21 if (t4<10**6).any() else float('nan'):.1f} mo) | "
          f"funded alive at end median {np.median(nf):.0f} | buy month (median) {[round(b,1) for b in btimes]} funded month {[round(f,1) if f else None for f in ftimes]} | "
          f"burned funded avg {np.mean([r['burns'] for r in R]):.2f} failed challenges avg {np.mean([r['fails'] for r in R]):.2f} ({len(starts)} paths)", flush=True)


if __name__ == "__main__":
    base = F.days
    for c in (0, 1000, 3000, 6000):
        summary(base, f"cushion ${c}", cushion=c)
    summary(base, "buy all 4 now (out of pocket)", buy_all=True)
    summary(base, "only 1 account forever", target=1)
    weak = F.make_days(7.0)
    print("--- edge 20% weaker (cost +2) ---")
    for c in (1000, 3000):
        summary(weak, f"weak: cushion ${c}", cushion=c)
    summary(weak, "weak: buy all 4 now", buy_all=True)
