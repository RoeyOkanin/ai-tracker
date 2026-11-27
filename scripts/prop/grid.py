import sys, pickle, itertools
from strategies import load, noise_momentum
P = "/tmp/claude-0/-home-claude/ce79a1f4-33d1-50c2-a5ff-d015937a8644/scratchpad/grid/"
sym, part, nparts = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
q = load(f"../../data/prop/{sym}_5m.csv.gz")
G = list(itertools.product((1.0, 1.25, 1.5), (14, 30), (30, 15), (0, 1)))
for i, (vm, lb, st, sd) in enumerate(G):
    if i % nparts != part:
        continue
    k = f"{sym}_vm{vm}_lb{lb}_st{st}_side{sd}"
    pickle.dump(noise_momentum(q, lookback=lb, vm=vm, step=st, side=sd), open(P + k + ".pkl", "wb"))
    print(k, flush=True)
