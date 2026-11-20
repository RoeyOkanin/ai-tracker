# MT5 harness: run the real EA source under g++

Runs `mt5/IntradayMomentum.mq5` itself (not a Python re-implementation) against simulated US100.cash bars,
so EA bugs can be found and fixed before they cost a challenge.

- `prep_mq5.py` turns the `.mq5` into a C++ struct with mechanical rewrites only (arrays become bounds-checked
  like MQL5, `input` becomes a member, `PrintFormat` arguments are type-checked by `-Wformat`).
- `mql_shim.h` is a small MQL5 runtime with a simulated broker: FTMO server time (New York + 7h), a hedging
  account, market orders, server-side stops, deal history, terminal global variables, and
  "market closed" when there is no bar. MQL5 enums are typed, so passing the wrong property to a function
  does not compile.
- `driver.cpp` feeds ticks and timer events, can inject faults, restarts, VPS downtime and slippage, and
  checks FTMO's limits: daily loss is measured against the balance at 00:00 Prague time, max loss against
  the initial balance, both on equity.
- `export_bars.py`: QQQ 5-min bars x41 with server timestamps. `research` = the research data as is.
  `cfd` = half-days stop at 13:15 NY like the CFD. `hol=DATE:TEMPLATE` adds a synthetic futures-only holiday morning.
- `ea_port.py` / `compare_A1.py`: day-by-day check against the Python port that matches the research backtest.
- `mc.py`: challenge Monte Carlo with the real code. It starts on the first trading day of each month from
  2016-04 to 2025-11 and runs phase 1 (10%) and then phase 2 (5%). Costs scale with the index level
  (1.2 bp spread + 0.8 bp exit slippage, about 5 pts at 25,000).
- `scen.sh`: runs one scenario on v2.00 and on v2.01 and prints the key log lines and trades.

```
./build.sh                                   # needs g++ (C++17), python3, pandas; writes build/
cd build
./driver ver=v201 bars=bars_cfd.csv from=2025-11-24 to=2025-12-02 tstep=60 log=x.log trades=x.csv
python3 ../mc.py v201 dense=10               # about 2.5 minutes on 4 cores
../scen.sh NAME from=... to=... [fault=closes,NYfrom,NYto,rc] [restart=NYtime] [eadead=NYfrom,NYto] [slip=pts]
```

## Results (2026-11-20)

- **Same trades as the research.** With the calendar off and the guards disabled, the v2.01 code produces the
  same 2,002 trades as the research port on all 2,676 days from 2016-04 to 2026-11: same side, entry time
  and exit time. Total P&L is within 0.04% (lot rounding). v2.00 produces the same trades too, so v2.01
  changes no trading rule.
- **v2.00 bugs reproduced with the real code:**
  - Holiday trading. On a synthetic Thanksgiving 2025 morning it shorted 8.53 lots, was stuck when the
    market closed at 13:00 and carried the position into the next day (-$3,461 in the example).
  - Request spam. It made 28,861 close requests in one day while the market was closed, against
    FTMO's 2,000 per day. Over 2016-2026, with half-days ending at 13:15, it made 408k requests in total.
  - Positions held through closures. It held 8 positions for 45 to 96 hours (Jul 3, Black Friday, Dec 24).
  - Restart after the daily guard. The guard was undone and the EA traded again the same day.
  - VPS down after an earlier loss. The server stop ignored that loss, and the day breached FTMO's
    daily limit on 2025-11-18 (equity 93,215 < 93,733).
  - A rejected exit at a reversal. It opened the opposite side anyway, so long and short were open together,
    and the hidden long hit its stop (-$4,505 instead of -$2,545).
  - A slipped profit-target close. It marked the target done below the target and stopped trading for good.
- **A v2.01 bug found and fixed:** the first daily request cap (300) plus 5-second retries blocked the
  end-of-day close after 25 minutes of rejections, and the position stayed open overnight. Fixed with
  5 s to 60 s backoff, a cap of 1,000, and terminal-side rejections no longer counted. Now: 36 requests,
  closed right after the rejections ended.
- **Challenge Monte Carlo (real v2.01, dense ticks, 116 starts):** phase 1 83%, both phases 74%,
  **both within 12 months 72%**, median 5.1 months, **0 FTMO breaches**, at most 8 requests per day.
  With coarse ticks (5 per bar) 6 runs breached, but these were 2 events where price jumped through the
  guard between two ticks. With a guard of 4.0% or 3.5% the pass rate does not get better.
