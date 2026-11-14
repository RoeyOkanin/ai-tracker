# Prop-firm strategy research (2026-11-13)

Data: QQQ 5-min RTH bars 2016-01 .. 2026-11 (Alpaca SIP), converted to NQ points
(NQ/QQQ ~ 41.4) and rescaled to today's NQ level (~25,000) so every year is sized
at constant notional. Costs: $2.50 round turn per MNQ (Apex), 1.5 NQ pts spread (FTMO CFD).

Strategies (scripts/prop/strategies.py):
- `noise_vwap`: Zarattini/Aziz/Barbon "Beat the Market" intraday momentum (14-day noise
  band, entries on :00/:30 from 10:00, stop = max(band, VWAP), flat 15:55). `_vt` = vol-targeted.
- `orb*`: Zarattini/Aziz opening-range breakout (5/15/30-min, 10R target or EOD).

Rule simulators (scripts/prop/propsim.py): Apex 50K EOD eval + PA (2026 rules: $2,000 EOD trail,
$1,000 DLL, 30 days, 5 qualifying days, 50% consistency, 6 payout caps) and FTMO 2-Step 100K
(10%/5% targets, 5% daily equity loss, 10% static, 4 min days). An attempt starts on every day.

Headline (noise_vwap_vt):
- Per 1 MNQ: +$26/day, sd $270, Sharpe 1.54, max DD $3,941, positive in all 11 years.
- Apex 50K eval @4-6 MNQ: pass ~32%. PA @1 MNQ: 61% get >=1 payout, avg $2.3k/yr, 46% breach in 1y.
- FTMO 2-Step 100K @ $8/pt: pass 67% (avg ~127 trading days for both phases); funded @ $5/pt:
  avg $13k/yr paid, 10% breach. With 3-pt costs: pass 61%, funded $12k.
- Weak years for new attempts: 2016, 2025.

Repro: python fetch_intraday.py (Actions) -> run_strats.py -> normalize.py -> run_all.py

## FTMO Standard (non-Swing) check (2026-11-14)
Funded Standard accounts may not open/close US100 within 2 minutes of restricted news; evaluation
has no news rule. Conservative fix: move the 10:00 and 14:00 ET checkpoints to 10:05 / 14:05 every day
(`noise_momentum(shift=...)`). Cost: Sharpe 1.54 -> 1.28, 10/11 years positive (2019 slightly negative);
funded @ $5/pt $13.2k -> $11.0k/yr, breach 10% -> 12%. Targets and payout timing are the same as Swing.
Speed comes from evaluation size, not account type: 2-Step @ $12/pt passes 54% (median 75 trading days);
with immediate retries 91% are funded within 12 months and net ~$5.4k in year one (run_speed.py).

## Improvement attempts (2026-11-14)
- Parameter grid (band width 1/1.25/1.5, lookback 14/30, checks 15/30 min, long-only) on QQQ and SPY,
  tuned 2016-21, tested 2022-26 (grid.py, grid_eval.py): IS-best variants are worse OOS than the paper's
  defaults (QQQ base OOS Sharpe 1.61). Keep defaults.
- Other markets (combo.py): net Sharpe NQ 1.31, ES 0.68, RTY -0.64, YM -0.15, gold -0.46, oil -1.12.
  Every blend is worse than NQ alone. Trade US100 only. (Edge is concentrated in one market: a risk.)
- Overnight long QQQ: Sharpe 0.56 after 2bp/night financing, 2022 -27%. Rejected.
- Funded-account sizing scaled by distance to the 10% floor (size x buffer/10%, min 25%; run_dyn.py):
  funded @ $8/pt -> $15.7k/yr, 0% breach in 1y, vs fixed $5/pt $13.2k, 10% breach. Adopted.
- Plan (run_plan.py): eval $12/pt fixed, funded $8/pt buffer-scaled: 91% funded within 12m,
  year-1 net avg $8.3k (vs $6.4k). Eval $15/pt: $9.2k avg, median day 80, 21% chance year-1 loss.
- Margin cap check (run_leverage.py): no effect down to 1:7 index leverage; at 1:5 eval pass 55% but median 89 vs 75 days; funded unchanged.
