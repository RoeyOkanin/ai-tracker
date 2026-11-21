from sim import *
import sys
base_old = build("base")
new = build("b12_14")
print("OLD EA logic (no time block, no skip), $12:", fmt(evaluate(base_old, fixed(12), skip_th=0)[0]), flush=True)
print("CURRENT EA (block 12/14 + skip 167), $12:", fmt(evaluate(new, fixed(12))[0]), flush=True)
for X in (4, 5, 6, 7, 8, 9, 10):
    print(f"CURRENT EA ${X}:", fmt(evaluate(new, fixed(X))[0]), flush=True)
print("CURRENT EA $12 + target stop:", fmt(evaluate(new, fixed(12), target_stop=True)[0]), flush=True)
