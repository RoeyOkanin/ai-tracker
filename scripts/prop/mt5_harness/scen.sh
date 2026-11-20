#!/bin/bash
# usage: scen.sh NAME "driver args"   -> runs v200, v201 and v202 (or $VERS), prints key log lines and trades
N=$1; shift
cd "$(dirname "$0")/build" || exit 1
for v in ${VERS:-v200 v201 v202}; do
  ./driver ver=$v bars=bars_cfd.csv tstep=60 in.InpLogCsv=false trades=sc_${N}_$v.csv log=sc_${N}_$v.log "$@" > sc_${N}_$v.out
  echo "##### $N $v"; grep -E "SUMMARY|REQUESTS|^FTMO" sc_${N}_$v.out | sed 's/ticks=.*minEq/minEq/'
  grep -vE "FLAT|FTMO day|trend:|ready:|today open|start:|v2.01 start|no-trade days" sc_${N}_$v.log | awk '/close failed|EOD EXIT|retry/{n[$0~/close failed/]++; if(n[$0~/close failed/]>4) next} {print}' | cut -c1-200 | head -${LINES_MAX:-25}
  echo "  trades:"; tail -n +2 sc_${N}_$v.csv | awk -F, '{printf "   side=%s in=%s out=%s vol=%s pnl=%s why=%s sl=%s\n",$2,strftime("%m-%d %H:%M:%S",$3-7*3600,1),($4>0?strftime("%m-%d %H:%M:%S",$4-7*3600,1):"OPEN"),$7,$8,$9,$11}'
done
