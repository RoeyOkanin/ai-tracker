#!/bin/bash
# Runs every bug-hunt scenario (rounds 1-5) on two EA versions and says whether trades and FTMO/request
# summaries are identical. usage: ./regress.sh [VA] [VB]   (default v203 v204; run ./build.sh first)
VA=${1:-v203}; VB=${2:-v204}
cd "$(dirname "$0")/build" || exit 1
[ -f bars_cfd_hol.csv ] || python3 ../export_bars.py cfd bars_cfd_hol.csv hol=2025-11-27:2025-11-06 > /dev/null
mkdir -p regress
run() {
  name=$1; shift
  [ -n "$ONLY" ] && [[ ! " $ONLY " =~ " $name " ]] && return     # ONLY="S3 LT15" ./regress.sh runs just these rows
  for v in $VA $VB; do ./driver ver=$v tstep=60 in.InpLogCsv=false trades=regress/${name}_$v.csv log=regress/${name}_$v.log "$@" > regress/${name}_$v.out 2>&1 & done; wait
  sum() { grep -E 'SUMMARY|FTMO d|REQUESTS' regress/${name}_$1.out | sed 's/ver=v[0-9]* //; s/ticks=[0-9]* timers=[0-9]* //'; }
  res() { echo "$(grep SUMMARY regress/${name}_$1.out | grep -o 'balance=[0-9.]*') $(grep -o 'deals=[0-9]*' regress/${name}_$1.out) $(grep -o 'daily_breach_ticks=[0-9]*' regress/${name}_$1.out) $(grep -o 'max_positions=[0-9]*' regress/${name}_$1.out)"; }
  a=$(tail -n +2 regress/${name}_$VA.csv | md5sum); b=$(tail -n +2 regress/${name}_$VB.csv | md5sum)
  printf "%-5s trades %-4s | summary %-4s | %s: %s | %s: %s\n" $name $([ "$a" == "$b" ] && echo same || echo DIFF) \
    $([ "$(sum $VA)" == "$(sum $VB)" ] && echo same || echo DIFF) \
    $VA "$(res $VA)" $VB "$(res $VB)"
}
# round 1
run S3   bars=bars_cfd.csv from=2024-03-07 to=2024-03-08 in.InpTargetPct=0 fault=closes,2024-03-08T11:29:00,2024-03-08T11:30:30,10006
run S4a  bars=bars_cfd.csv from=2025-11-20 to=2025-11-26 in.InpTargetPct=4 slip=40
run S4b  bars=bars_cfd.csv from=2025-11-20 to=2025-11-26 in.InpTargetPct=4 slip=8
run S6   bars=bars_cfd.csv from=2025-11-19 to=2025-11-20 in.InpTargetPct=0 fault=opens,2025-11-20T12:29:00,2025-11-20T12:30:05,10004
run S7   bars=bars_cfd.csv from=2025-11-17 to=2025-11-19 in.InpTargetPct=0 eadead=2025-11-18T12:31,2025-11-19T09:00
run S8   bars=bars_cfd.csv from=2026-06-10 to=2026-06-11 in.InpTargetPct=0 in.InpDailyGuardPct=1.2 restart=2026-06-11T12:00
run S9   bars=bars_cfd.csv from=2025-11-20 to=2025-11-21 in.InpTargetPct=0 fault=closes,2025-11-20T15:50,2025-11-20T16:30,10006 timer1s=2025-11-20T15:50,2025-11-20T17:00
run S10  bars=bars_cfd.csv from=2025-11-20 to=2025-11-26 in.InpTargetPct=4.5 in.InpTargetBufferPct=5 restart=2025-11-25T10:15
run HOL  bars=bars_cfd_hol.csv from=2025-11-24 to=2025-12-02 timer1s=2025-11-27T00:00,2025-12-01T10:00 in.InpTargetPct=0
# round 2
run P3   bars=bars_cfd.csv from=2024-03-07 to=2024-03-08 in.InpTargetPct=0 fault=partial,2024-03-08T11:29:00,2024-03-08T11:30:30,0
run Q    bars=bars_cfd.csv from=2025-11-20 to=2025-11-21 "reinit=2025-11-20T10:15:00;InpDollarsPerPoint=8"
run H1   bars=bars_cfd.csv from=2025-01-02 to=2025-11-19 in.InpTargetPct=0 quiet=1 restart_daily=0929 hole_daily=0929,0945,1200
run H2   bars=bars_cfd.csv from=2025-01-02 to=2025-11-19 in.InpTargetPct=0 quiet=1 restart_daily=1107 hole_daily=1107,1112,1200
run H3   bars=bars_cfd.csv from=2025-01-02 to=2025-11-19 in.InpTargetPct=0 quiet=1 restart_daily=0929 hole_daily=0929,1010,1200
# round 3: restarts before the account is logged in (5 s)
C3="bars=bars_cfd.csv from=2025-01-02 to=2025-12-31 in.InpTargetPct=0 quiet=1 spread_bp=1.2 slip_bp=0.8"
run N5   $C3 restart_daily=2200 sync=5
run M5   $C3 restart_daily=0900 sync=5
run E5   $C3 restart_every=15 sync=5
run S8s  bars=bars_cfd.csv from=2026-06-10 to=2026-06-11 in.InpTargetPct=0 in.InpDailyGuardPct=1.2 restart=2026-06-11T12:00 sync=5
run S10s bars=bars_cfd.csv from=2025-11-20 to=2025-11-26 in.InpTargetPct=4.5 in.InpTargetBufferPct=5 restart=2025-11-25T10:15 sync=5
# round 4: terminal view lags OrderSend and freezes while disconnected (view=1)
run V1   $C3 view=1
run VE15 $C3 view=1 restart_every=15 sync=5
run DC1  $C3 view=1 disconnect_daily=102830,103300
run DC3  $C3 view=1 disconnect_daily=115500,124000
run DC4  $C3 view=1 disconnect_daily=130000,150000
run DCE  $C3 view=1 disconnect_daily=155700,160400
run AO   $C3 view=1 algooff_daily=155000,161000
run LEV  $C3 view=1 leverage=3
run VM   $C3 view=1 volmax=5
# round 5: entry orders that time out and are executed later, orders executed although OrderSend failed,
# trade state reaching the terminal late, account data reading 0 while the EA runs (rows LT.., GH12, RL.., EQ0 differ by design).
# The retry runs on the EA's 1-second timer, so these rows need dense ticks (dense=5).
Y="2025-01-01T00:00:00,2025-12-31T23:59:59"
run LT15 $C3 view=1 dense=5 fault=late,$Y,10012,15
run LT45 $C3 view=1 dense=5 fault=late,$Y,10012,45
run GH12 $C3 dense=5 tradelag=15 fault=ghost,$Y,10012
run GH31 $C3 dense=5 tradelag=15 fault=ghost,$Y,10031
run TL3  $C3 dense=5 tradelag=3 ballag=5
run RL09 $C3 view=1 relogin_daily=095000,095005
run RL11 $C3 view=1 relogin_daily=110000,110005
run RL18 $C3 view=1 relogin_daily=180000,180010
run EQ0  $C3 view=1 eqzero_daily=095000,095003
