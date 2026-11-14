"""Quarterly refresh of the switch's stock list (data/research/broad_universe.csv).

Same rule that built the list, applied to today's US listings:
an industry in the AI chain, market cap >= $50M. New listings and companies whose
industry now falls in the chain come in; delisted names and names below $50M drop out.
Size and liquidity for trading are checked separately every day by the switch itself
(price >= $5 and >= $100M a day traded), so a name on the list is only bought when it
is big enough at that moment.

Safety: if the new list is less than 80% of the old one, the listing source is
probably broken, and nothing is written.

Writes:
  data/research/broad_universe.csv      the new list
  data/research/universe_changes.csv    append-only: date, added, removed
  $NOTIFY_PATH                          a short Hebrew note when something changed
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import date

import pandas as pd

from broad_research import build_universe
from bottleneck_research import OUT, PHYS


def main() -> int:
    path = OUT / "broad_universe.csv"
    old = pd.read_csv(path)
    new = build_universe()
    if len(new) < 0.8 * len(old):
        print(f"refusing: new list has {len(new)} names vs {len(old)} before; listing source looks broken")
        return 1
    o, n = set(old["ticker"]), set(new["ticker"])
    phys_new = set(new.loc[new["bucket"].isin(PHYS), "ticker"])
    phys_old = set(old.loc[old["bucket"].isin(PHYS), "ticker"])
    added, removed = sorted(phys_new - phys_old), sorted(phys_old - phys_new)
    new.to_csv(path, index=False)
    log = OUT / "universe_changes.csv"
    first = not log.exists()
    with log.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if first:
            w.writerow(["date", "names_total", "chain_names", "added", "removed"])
        w.writerow([date.today().isoformat(), len(n), len(phys_new), " ".join(added), " ".join(removed)])
    print(f"list: {len(o)} -> {len(n)} names; physical chain {len(phys_old)} -> {len(phys_new)}; "
          f"+{len(added)} -{len(removed)}")
    print("added:", added)
    print("removed:", removed)
    note = os.environ.get("NOTIFY_PATH")
    if note and (added or removed):
        name = dict(zip(new["ticker"], new["name"]))
        oname = dict(zip(old["ticker"], old["name"]))
        lines = [f"### רענון רבעוני של רשימת המניות: {len(phys_old)} ← {len(phys_new)}",
                 "המתג יכול לבחור מעכשיו גם מהמניות שנכנסו. מניה נקנית רק כשהיא גם נסחרת ב-$100M ביום ומעל ממוצע 200.", ""]
        if added:
            lines += [f"**נכנסו ({len(added)}):** " + ", ".join(f"{t} ({str(name.get(t, ''))[:30]})" for t in added[:60])]
        if removed:
            lines += [f"**יצאו ({len(removed)}):** " + ", ".join(f"{t} ({str(oname.get(t, ''))[:30]})" for t in removed[:60])]
        with open(note, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
