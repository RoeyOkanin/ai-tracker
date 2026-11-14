# IntradayMomentum EA (MT5, FTMO US100.cash)

Same rules as `scripts/prop/strategies.py::noise_momentum` (vol-targeted, constant notional), see the
header of `IntradayMomentum.mq5`. Research results: `data/prop/README.md`.

Inputs to change per phase:
- Challenge / verification: `InpDollarsPerPoint=12`, `InpBufferScaling=false`.
- Funded: `InpDollarsPerPoint=8`, `InpBufferScaling=true`.
- `InpInitialBalance` = the account's starting balance.

Differences from the backtest (by design):
- VWAP uses tick volume (CFDs have no exchange volume).
- Flattens at 15:59 NY instead of the 16:00 bar close.
- Exit-and-re-enter on the same bar is a hold (same exposure, one spread less).
- Margin cap: never uses more than 80% of free margin (Swing has lower leverage); size is cut if needed.
- Safety not in the backtest: server-side stop at 4.5% of initial balance per position, and an equity guard
  that flattens and stops for the day 4.5% below the day-start balance (FTMO limit is 5%).

Strategy Tester: the tester cannot detect the server's UTC offset; set `InpServerWinterOffset` to the value
the EA prints live ("server winter offset=UTC+X"). Decisions are logged to `MQL5/Files/IntradayMomentum_log.csv`.

## Tester vs backtest check (2025-11 .. 2026-11, Strategy Tester real ticks)
- EA v1: +$10.4k vs python +$26.1k. 87 days with identical entries/exits differ by only -$1.7k in total.
- Cause of most of the gap: FTMO's server moves its clock on **US** DST dates (verified by matching
  US100.cash fills to QQQ prices), the EA assumed EU dates. In the two mismatch windows
  (2026-03-09..27, 2026-10-26..30) the EA traded one hour off: -$66 vs python +$10.9k.
  Fixed: `InpServerDstRule = 2` (US). Estimated full-year result after fix ~ +$21k.
- Remaining ~-$4.7k over 139 days (~$23/trade) = spread + US100.cash vs QQQ price differences.
- Drawdown this year is real in both: python -17.4k peak-to-trough, EA -23k. At $12/pt a challenge
  started Nov 2025 breaches the 10% limit in Jan-Feb 2026.
- After the fix (InpServerDstRule=2): tester +$16.8k, Sharpe 2.10, PF 1.14, equity DD 23.9%.
  Remaining gap to python ~3.5 pts/trade of extra cost. Re-run with cost 5 pts: scripts/prop/run_live_cost.py,
  data/prop/results_live_cost.txt (eval $12/pt: 43% single pass, 89% funded <12m with retries, funded yr ~$11.7k avg).
