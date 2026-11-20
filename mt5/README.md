# IntradayMomentum EA (MT5, FTMO US100.cash)

Same rules as `scripts/prop/strategies.py::noise_momentum` (vol-targeted, constant notional), see the
header of `IntradayMomentum.mq5`. Research results: `data/prop/README.md`.

Inputs to change per phase (v2.01, everything else at its default):
- Phase 1: `InpTargetPct=10`. Phase 2: `InpTargetPct=5`. Both at `InpDollarsPerPoint=10`.
- Funded: `InpTargetPct=0`, `InpDollarsPerPoint=8`, `InpBufferScaling=true`.
- `InpInitialBalance` = the account's starting balance.
- After replacing the file and compiling, press **Reset** in the EA's Inputs tab so new inputs get their defaults.

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

## v2.00 (2026-11-14): goal = 70% chance to pass the FTMO 2-Step in one attempt
New challenge simulator (scripts/prop/goal70/sim.py) mirrors the EA: guards, skip-after-win, 12:00/14:00 block,
cost 5 pts x vol-scale per trade, optional intraday target stop. Start on every 2nd trading day 2016-2025.
"12m" = passed both phases within 252 trading days; "24m" = eventual pass (FTMO has no time limit).

| config | 12m pass | 24m pass | 2016-21 / 2022-26 (12m) | median days |
|---|---|---|---|---|
| v1 EA ($12, vol cap 2, no target stop) | 55.6% | 60.3% | 46.0 / 70.3 | 75 |
| **v2 Balanced** ($10, cap 1, x1.5 below MA50, target stop) | **75.8%** | **84.8%** | 69.4 / 85.6 | 101 |
| v2 Safe ($8, cap 1, x1.25 below MA50, target stop) | 73.2% | 94.1% | 69.9 / 78.1 | 158 |

- Cross-validated (pick the config on one half, score it on the other): **73.8%** within 12 months.
- Cost stress: at 6 pts/trade Balanced 72.7% / 83.4%; at 7 pts 65.6% / 76.7%.
- Kept: vol cap 1.0 (Sharpe 2016-21 0.79 -> 0.92, 2022-26 1.31 -> 1.32, lower DD in both); trend tilt
  (x1.25-1.5 below MA20..200 all help 2016-21, neutral 2022-26); target stop (+2-5 pts, ~20% faster).
- Rejected: max entries/day, cushion (distance-to-floor) sizing in the challenge, phase-specific sizes
  (flat plateau), equity-curve filters, adding SPY/DIA/IWM/GLD streams (all lower Sharpe), start-date timing
  (pass rate does not depend on the regime at the start).
- Funded with v2: $8/pt + InpBufferScaling, target 0 -> ~$15.5k/yr avg per 100K, 0% breach (2016-2026 starts).
- Strategy Tester full-year runs: set InpTargetPct = 0, otherwise the EA stops at +10%.
  Python expectations (v2 Balanced, target off): 2024 +$32.7k (DD -8.1k), 2025 +$25.1k (DD -15.0k),
  2025-11..2026-11 +$20.9k (DD -11.6k, lowest -8.5k vs start).

Inputs per account: phase 1 `InpTargetPct=10`, phase 2 `InpTargetPct=5` (both $10), funded `InpTargetPct=0`,
`InpDollarsPerPoint=8`, `InpBufferScaling=true`.

## v2.01 (2026-11-20): bug fixes before buying the challenge, trading rules unchanged
Found by running the EA source itself in `scripts/prop/mt5_harness` (g++ shim with a simulated FTMO broker).
With the calendar off, v2.00 and v2.01 make the same 2,002 trades as the research on all 2,676 days (2016-04..2026-11).

| # | v2.00 bug (reproduced with the real code) | v2.01 fix |
|---|---|---|
| 1 | No US holiday calendar. It trades the futures-only holiday mornings (US100.cash closes 13:00 NY) and the half-days (day after Thanksgiving, Dec 24, Jul 3: CFD stops 13:15 NY). Positions get stuck through the closure (8 held 45-96 h in 2016-26; example Thanksgiving short -$3,461). Holiday bars also enter the band/vol/MA history. Holding through a closure can count as FTMO "gap trading". | NYSE calendar (holidays, half-days, `InpExtraClosedDays`). No trading on those days. Holiday sessions are left out of the history. Anything open outside 09:30-15:59 NY on a trading day is closed at the first tick. |
| 2 | The EOD close is retried every second while the market is closed: 28,861 requests in one day (FTMO: more than 2,000 server requests per day is forbidden). | Backoff 5, 10, 20, 40, then 60 s. After "market closed" it retries on the next tick only. Cap `InpMaxRequestsPerDay=1000`, and terminal-side rejections are not counted. |
| 3 | A rejected exit is logged as done and the opposite side is opened anyway: long and short open together, the hidden long hit its stop (-$4,505 vs -$2,545). | Nothing new opens while an exit is pending. The reversal is taken only if flat within 60 s. Transient entry failures are retried for 60 s. |
| 4 | A restart resets the daily-loss reference to the current balance and clears the guard. After a guard hit, the EA traded again the same day. | Daily reference = balance at 00:00 Prague time (FTMO's reset), stored in a terminal global variable. The guard day is stored too. |
| 5 | The server-side stop is always 4.5% of initial and ignores the day's earlier losses. With the VPS down after a morning loss, 2025-11-18 breached FTMO's daily limit. | The stop never allows more than the room left to the daily limit (guard + 0.25%) and to the max-loss floor. |
| 6 | Profit target: marked done even if the close slipped below the target, so it stops trading for good below the target. A failed close was never retried. | Closes are retried until flat. Done only when the closed balance is at or above the target. It also handles a restart with a micro trade open. |
| 7 | With less than 50 sessions of M5 history the MA50 tilt was silently skipped. | It retries every minute until 09:55, then trades with a WARNING in the log. |
| 8 | No symbol check. | Refuses to start unless the chart symbol contains US100. |

Also found and fixed during testing of v2.01 itself: the first request cap (300) plus 5 s retries locked the
end-of-day close after 25 minutes of rejections, so the position stayed overnight. That is why the backoff above exists.

Optional, off by default: `InpPreCloseLastEntry` (HHMM), no new entries after that time when the market then
closes for more than 2 h (Fridays, before Good Friday, Christmas or New Year). 14:30 cost about 1 point of pass rate.

Honest pass rate (real v2.01 code, 116 monthly starts 2016-04..2025-11, costs ~5 pts at 25,000, half-days
not traded): phase 1 83%, both phases 74%, **both within 12 months 72%**, median 5.1 months, 0 FTMO breaches.
The 75.8% / 84.8% above included phantom post-market P&L on half-days in the research data.

Check after installing (Experts tab):
- `[IMOM] v2.01 start: ... server winter offset=UTC+2 ...`
- `[IMOM] FTMO day YYYYMMDD: start balance ...`
- `[IMOM] no-trade days in the next 45 days: 20261126=holiday 20261127=early-close 20261224=early-close 20261225=holiday 20270101=holiday`
