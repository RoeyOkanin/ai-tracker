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
