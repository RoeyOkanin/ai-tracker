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
- `scen.sh`: runs one scenario on v2.00, v2.01 and v2.02 (or `VERS="v202 v203"`) and prints the key log lines and trades.
- `cmp_trades.py A.csv B.csv`: day-by-day comparison of two trade files (side, entry, exit, volume, P&L).
- `regress.sh [VA] [VB]`: every bug-hunt scenario on two versions, same/DIFF per scenario.
- `cal_check.py`: the EA's NYSE calendar (real code, `build/cal_check`) against the official XNYS calendar 2016-2035
  (`pip install exchange_calendars`).

Driver options added for the second bug hunt (v2.02):
- `reinit=YYYY-MM-DDTHH:MM:SS;Name=Value;...` changes inputs on the running EA object like MT5 does
  (OnDeinit(REASON_PARAMETERS) + OnInit, the program stays loaded and keeps its global variables).
- `restart_daily=HHMM[,HHMM...]` / `restart_every=MIN`: restarts at these NY times on every session day.
- `hole_daily=HHMMfrom,HHMMto,PREVHHMM`: between HHMMfrom and HHMMto NY the terminal history misses the bars from the
  previous session's PREVHHMM until HHMMfrom (history still downloading after a restart).
- `fault=partial,NYfrom,NYto,0`: closes are accepted (OrderSend true, retcode 10010) but only half the volume is closed.

Driver option added for the third bug hunt (v2.03):
- `sync=SECONDS`: after each restart the terminal is not logged in yet for SECONDS, as after a real terminal or VPS
  start: ACCOUNT_LOGIN 0, balance/equity/free margin 0, no positions visible, TERMINAL_CONNECTED false, requests fail
  with 10031. The timer fires every second for 30 s after every start (EventSetTimer(1)).

Driver options added for the fourth bug hunt (round 4, no EA bug found):
- `view=1`: the EA sees the trade state as of the start of each event. Its own OrderSend results (positions, balance,
  free margin, deal history) show up from the next tick or timer event on, as MT5 updates the trade environment
  asynchronously. While disconnected no ticks reach the terminal and prices, bars, account and positions stay frozen;
  the server keeps running (stops, FTMO checks). `view=0` (default) gives exactly the earlier results.
- `disconnect_daily=HHMMSS,HHMMSS` / `algooff_daily=HHMMSS,HHMMSS`: a disconnect or Algo Trading off at these NY times
  on every session day. `leverage=N` (default 30) for the margin cap path.

```
./build.sh                                   # needs g++ (C++17), python3, pandas; writes build/
cd build
./driver ver=v202 bars=bars_cfd.csv from=2025-11-24 to=2025-12-02 tstep=60 log=x.log trades=x.csv
python3 ../mc.py v202 dense=10               # about 2.5 minutes on 4 cores
python3 ../cal_check.py
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

## Second bug hunt (2026-11-20, v2.02)

Four more bugs, each reproduced with the real v2.01 code, fixed in v2.02 (details in `mt5/README.md`):
- Input change at 10:15 ($10 -> $8, `reinit=`): v2.01 kept 14.94 lots for the rest of the day, v2.02 11.95.
- History still downloading after a restart (`hole_daily=`, every day of 2025, target off):
  restart 09:29 / history back 09:45: v2.01 91 of 123 days differ, v2.02 0;
  restart 11:07 / back 11:12: v2.01 57 days differ (-$16.0k), v2.02 0.
  History back only at 10:10 (after the wait): v2.02 trades exits only until then (no entries on stale data).
- Partly filled close at a reversal (`fault=partial`, 2024-03-08): v2.01 long and short open together, hidden long
  stopped out (-$2,252); v2.02 one position at a time, same balance as a clean exit (100,420.96).
- Funded size after restarts (`restart_every=30`, $8 + buffer scaling, 2016-2026): v2.01 185 days with a different
  size, v2.02 0.

No bug found:
- Restart every 15 min on every day of 2025 (3,200 restarts), challenge settings: 0 differences.
- Calendar vs XNYS 2016-2035: identical except the unscheduled closures 2018-12-05 and 2025-01-09.

Regression with v2.02: research equivalence 2,002 of 2,002 trades with `in.InpExtraClosedDays=20181205,20250109`
(2,001 without: 2025-01-10 is traded exits-only because the previous session is missing from the data).
All round-1 scenarios give the same results as v2.01. 10 years on CFD bars (calendar on): v2.01 and v2.02 identical
except 2025-01-10. Challenge Monte Carlo (real v2.02, dense ticks, 116 starts): phase 1 83%, both phases 74%,
**both within 12 months 72%**, median 5.1 months, 0 FTMO breaches, at most 8 requests per day (same as v2.01).

## Third bug hunt (2026-11-20, v2.03)

One more bug, reproduced with the real v2.02 code and fixed in v2.03 (details in `mt5/README.md`):
- Restart before the account is logged in (`sync=5`, 2025, $10/pt, target off). Earlier restart tests had the
  account loaded at once, so they could not show it. v2.02 saved an FTMO day start of 0 (daily guard off) or fired
  the guard on equity 0 (no entries that day):
  `restart_daily=2200` -> FTMO daily-loss breach on 2025-11-18; `restart_daily=0900` -> 0 trades in 2025;
  `restart_every=15` -> 0 trades. v2.03: all three, and `restart_every=15 sync=60`, give the same 179 trades as
  the run without restarts.

Regression with v2.03 (same commands as above):
- Research equivalence: 2,001 of 2,002 trades (2,002 of 2,002 with the extra closed days), same as v2.02.
- CFD bars, calendar on, 2016-2026: identical to v2.02 (2,004 trades).
- Funded ($8, buffer scaling), restart every 30 min with a 5 s login, 2016-2026: identical to the run without restarts.
- All scenarios of rounds 1-2 (`./regress.sh v202 v203`): same trades as v2.02, except the restart during a micro
  trade, which closes 5 s later ($0.04). The round-3 rows (N5, M5, E5) show the bug in v2.02 and none in v2.03.
- Challenge Monte Carlo (real v2.03, dense ticks, 116 starts): phase 1 83%, both phases 74%, both within 12 months
  72%, median 5.1 months, 0 FTMO breaches, at most 8 requests per day (same as v2.02).
- Same Monte Carlo with a restart every night (`restart_daily=2200 sync=5`): v2.02 32 of 116 challenges fail on the
  daily-loss limit (both within 12 months 53%); v2.03 0 failures, 72% (identical to no restarts).

## Round 4 (2026-11-20): no bug found in v2.03

- `view=0` reproduces every earlier scenario exactly (all `regress.sh` outputs byte-identical to round 3).
- `view=1`, v2.03: 10 years 2016-2026 on the research bars, 3 of 1,990 trades re-enter 1 s later (a close is only
  visible on the next event, so the reversal waits one event; $28 in total). 2025 with costs (`spread_bp=1.2
  slip_bp=0.8`), with nightly restarts or restarts every 15 min: identical trades to `view=0`.
- 2025, `view=1`: disconnect every day 10:28:30-10:33, 11:55-12:40, 13:00-15:00 or 15:57-16:04; Algo Trading off every
  day 15:50-16:10; leverage 1:3 (margin cap fired 42 times); volume cap 5 lots: 0 FTMO breaches, no position left
  open at the end, no runtime error, at most 9 requests per day.
- Challenge Monte Carlo `mc.py v203 dense=10 view=1`: phase 1 83%, both 74%, both within 12 months 72%, 0 breaches.
  Adding `restart_daily=2200 sync=5 disconnect_daily=102830,103300` (every 10:30 decision lost): 83% / 72% / 71%, 0 breaches.
- Worst FTMO day in 2025 with costs: $4,896 with the default 5 ticks per bar (the guard closes at the next tick, up to
  75 s after crossing $4,500), $4,647 with `dense=10`, $4,536 with `dense=1`. The research-bar 10-year run shows one
  daily breach (2022-01-28, $5,016, 23.7 lots) only with 5 ticks per bar: a price jump between two ticks 75 s apart.
