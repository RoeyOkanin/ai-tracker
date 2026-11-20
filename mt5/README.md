# IntradayMomentum EA (MT5, FTMO US100.cash)

Same rules as `scripts/prop/strategies.py::noise_momentum` (vol-targeted, constant notional), see the
header of `IntradayMomentum.mq5`. Research results: `data/prop/README.md`.

Inputs to change per phase (v2.03, everything else at its default):
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
the EA prints live ("server UTC+X (winter)" in the "account loaded" line). Decisions are logged to `MQL5/Files/IntradayMomentum_log.csv`.

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
- `[IMOM] v2.03 start: symbol=US100.cash magic=26111401, waiting for the account to load`
- `[IMOM] no-trade days in the next 45 days: 20261126=holiday 20261127=early-close 20261224=early-close 20261225=holiday 20270101=holiday`
- about 5 s later: `[IMOM] account <login> loaded: balance ..., FTMO day start ..., server UTC+2 (winter), New York now <NY time>, $/pt/lot=1.0000, lots min/step/max=...`

## v2.02 (2026-11-20): second bug hunt, trading rules unchanged
Same harness, new scenarios (`scripts/prop/mt5_harness`, see its README). Each bug was reproduced with the real v2.01 code.

| # | v2.01 bug (reproduced with the real code) | v2.02 fix |
|---|---|---|
| 9 | MT5 does not reload an EA when its inputs or the chart change (OnDeinit + OnInit only, globals keep their values; MQL5 book, "program life cycle"). Changing `InpDollarsPerPoint` 10 -> 8 at 10:15 still traded 14.94 lots at 12:30 instead of 11.95; the new size applied only the next day. | `ResetState()` at the start of OnInit: the day is prepared again with the new inputs at once (11.95 lots). Guard day and FTMO anchor are restored from the global variables, the target state from the closed balance. |
| 10 | After a restart the terminal may still be downloading M5 history. The day was prepared once with whatever was there: with yesterday's afternoon missing, prevClose, sigma and vol were wrong for the whole day. Restart at 09:29 with history back at 09:45, every day of 2025: trades differed on 91 of 123 days. Restart at 11:07, history back at 11:12: 57 days differed, -$16.0k. | The day is prepared only when yesterday's NYSE session is in the history and complete (its 15:55 bar, 12:55 on early-close days). Waits until 09:55 or 10 min after a restart; if still incomplete: exits only, no new entries, prepared again every minute. Both scenarios: 0 differences. |
| 11 | A close that is only partly filled (`OrderSend` true, retcode 10010) counted as done: at a reversal it opened the short while half of the long was still open; the hidden long hit its server stop (-$2,252). | An exit counts only if no position is left; otherwise it is retried and the reversal is taken within 60 s once flat. `OpenPos` refuses to open while any EA position exists. Same scenario: one position at a time, same result as a clean exit. |
| 12 | Funded buffer scaling used the balance at the moment the day was prepared, so a restart after a closed trade changed the size for the rest of the day (restarts every 30 min, funded $8, 2016-2026: 185 days with a different size). | Uses the balance before today's trades (balance - today's closed P&L of the EA): 0 days different. |

Also: the "previous session" check knows only scheduled NYSE holidays. On the day after an unscheduled closure
(national mourning: 2018-12-05, 2025-01-09) it trades exits only, unless the date is in `InpExtraClosedDays`.
In 2016-2026 this skipped one trade (2025-01-10, +$253).

Checks that found nothing:
- NYSE calendar (real EA code) vs the official XNYS calendar (`exchange_calendars`) 2016-2035: 0 differences
  except the 2 unscheduled closures above; 42 early closes match.
- Restart every 15 min (09:20-16:10 NY) on every day of 2025, challenge settings: 0 differences in 3,200 restarts.
- Extended-hours bars (pre-market from 04:00, post-market to 20:00 NY) were already in every test: no effect.
- All earlier scenarios (rejected exit at a reversal, target slip, requote, VPS down, restart after the guard,
  EOD close rejected 40 min, restart during a micro trade, Thanksgiving): same results as v2.01.

Regression: research equivalence (calendar off, guards off, 2016-04..2026-11) 2,001 of 2,002 trades identical
(the other is 2025-01-10 above; 2,002 of 2,002 with `InpExtraClosedDays=20181205,20250109`). CFD bars with the
calendar on, 10 years: v2.01 and v2.02 identical except 2025-01-10. Challenge Monte Carlo with the real v2.02
(116 monthly starts, dense ticks): phase 1 83%, both phases 74%, both within 12 months 72%, 0 FTMO breaches,
at most 8 requests per day: unchanged.

Known limits (not fixed): a 5-minute bar with no ticks at all just before a decision time skips that decision;
two terminals or two charts running the EA on the same account would both trade (keep the home MT5 closed).

## v2.03 (2026-11-20): third bug hunt, trading rules unchanged
Round 3 looked for what the harness could not see: MT5 runtime behaviour around a terminal or VPS start. The
harness now has `sync=SECONDS`: after each restart the terminal is not logged in yet for that long (login 0,
balance and equity 0, no positions, requests fail with 10031). The MQL5 forum documents this state: ACCOUNT_LOGIN
reads 0 for about 5 s after a terminal start, and account data is only valid once the terminal has connected.

| # | v2.02 bug (reproduced with the real code) | v2.03 fix |
|---|---|---|
| 13 | After a terminal/VPS restart MT5 runs OnInit and the first OnTimer calls before the account is logged in. v2.02 (a) looked for the saved FTMO day start under login 0, did not find it, and saved a day start of 0 for the whole FTMO day: the daily equity guard was off and the server stop ignored the day's losses; (b) read equity 0 and fired the equity guard, which blocks entries for the rest of the New York day. 2025, $10/pt, target off, login 5 s after each restart: restart every night at 22:00 NY -> **FTMO daily-loss breach on 2025-11-18** (equity 120,889 < 125,952 - 5,000); restart at 09:00 NY -> **0 trades in the whole year**; restart every 15 min -> 0 trades. | Nothing that uses the account (guard, target, day start, sizing, orders) runs until the terminal is connected and login, balance and price have been valid for 5 s. Then the guard day and the day start are restored from the global variables of that account. The restored day start is never below what the deal history shows, and an account change without a reload starts over. Night, morning and every-15-min restarts, with a 5 s or a 60 s login: same trades as without restarts. |

Smaller changes: malformed `InpExtraClosedDays` entries print a warning instead of being dropped silently; the
"account loaded" line shows the symbol's volume limits, and a size capped by the maximum volume prints a warning.

Regression with v2.03: research equivalence 2,001 of 2,002 trades (2,002 of 2,002 with the two extra closed days),
same as v2.02. CFD bars, calendar on, 2016-2026: identical to v2.02. All scenarios of rounds 1 and 2 give the same
trades as v2.02, except the restart during a micro trade, which now closes 5 s later ($0.04).
Challenge Monte Carlo with the real v2.03 (116 monthly starts, dense ticks): phase 1 83%, both phases 74%,
**both within 12 months 72%**, median 5.1 months, 0 FTMO breaches, at most 8 requests per day: unchanged.
With a VPS restart every night at 22:00 NY and a 5 s login, the same Monte Carlo gives: v2.02 fails 32 of 116
challenges on FTMO's daily-loss limit (both phases within 12 months 53%); v2.03 0 failures, 72%, same as without restarts.

Known limits (not fixed): after a restart nothing happens for about 5 s once the account is loaded; a 5-minute bar
with no ticks at all just before a decision time skips that decision; two terminals or two charts running the EA on
the same account would both trade (keep the home MT5 closed, or remove the EA from its chart there). Funded only:
on a payout day the saved day start does not include the withdrawal, so the guard sees the payout as a loss and the
EA sits out that day (to fix before the first payout).

### Round 4 (2026-11-20): no bug found in v2.03

Round 4 looked for faults the harness still could not show, and found no bug in v2.03:
- MQL5 runtime errors that stop an EA ("zero divide", "array out of range"): every division has a guarded
  divisor, and every array access is bounds-checked in the harness; none fired in any run.
- Daylight saving time while the EA runs for weeks: server, New York and Prague times come from fixed DST rules
  (server on US dates, verified 14.11), not from a one-time detection, so a DST weekend needs no restart.
- MT5 updates positions, balance and deal history a moment after OrderSend returns, and while disconnected no ticks
  arrive and the terminal's view is frozen. The harness now models both (`view=1`). Results with v2.03: 10 years
  2016-2026, 3 of 1,990 trades re-enter 1 s later ($28 in total); 2025 with costs, nightly restarts or restarts
  every 15 min: identical trades. 2025 with a disconnect every day around 10:30, around 12:00-12:40, from 13:00 to
  15:00 or over the 15:59 exit, Algo Trading off every day 15:50-16:10, leverage 1:3, or a 5-lot volume cap:
  0 FTMO breaches, no position left open, at most 9 requests per day.
- Challenge Monte Carlo with `view=1` (116 starts): phase 1 83%, both phases 74%, both within 12 months 72%,
  0 breaches (unchanged). With a restart every night and the 10:30 decision lost to a disconnect every day: 71%, 0 breaches.

Still unverified, only possible in MT5 itself: MetaEditor compile, Strategy Tester run, live days on the Free Trial.
After the first live session, check the `day ... ready: ... sessions=N` line: N must be at least 50 (MA50). If the
log says `trend MA50 needs 50 sessions`, raise Tools > Options > Charts > Max bars in chart (100000 is enough).
