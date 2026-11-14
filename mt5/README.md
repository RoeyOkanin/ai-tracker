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
- Tester 2024: +$52.8k (python cost-5: +$41.8k), min equity -$2.2k. Tester 2025: +$8.1k, DD -$31.6k (python Jan-Oct +$9.4k, DD -$29.8k).
- Funded sizing changed to **$6/pt + InpBufferScaling=true** (cost 5: $9.5k/yr avg, 0% breach; $8/pt breaches 8%,
  incl. a funded account started Apr 2025).
- 2026-11-14: added `InpSkipAfterWinPts = 167` (skip the next day after a day that made > 167 pts x $/pt, i.e. $2,000 at $12).
  Tested in scripts/prop/regime_test.py: skipped days lose money at every threshold 1,000-3,000 in both 2016-21 and
  2022-26, 8 of 11 years. FTMO sim (cost 5): eval $12 single pass 43% -> 54%, median 114 -> 84 days, funded $6 $9.5k -> $11.9k/yr.
  Python per period with skip: 2024 +50.3k, 2025 +22.1k, 2025-11..2026-11 +16.6k.
- 2026-11-14: added `InpNoEntryTimes = "1200,1400"` (no new entries on the 12:00 and 14:00 NY bar closes; exits still run).
  scripts/prop/timing_test.py: those two entry times lose in both 2016-21 and 2022-26; day-of-week, OPEX and month-end are
  inconsistent between halves (not used). With skip-after-win: eval $12 single pass 56%, median 87 days, yr-1 net $7.1k,
  funded $6 $12.9k/yr, 0% breach. Caveat: skip-after-win alone raised the 2016-17 drawdown (-51k -> -65k at $12);
  with the time filter it is back to -52k.
