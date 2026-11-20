#!/bin/bash
# Build the harness: converts the EA versions to C++, compiles the driver, exports bar files.
# v2.00 = ran live until 2026-11-20 (commit 86af481), v2.01 = commit 7c1fcc6, v2.02 = commit e86a59d, v2.03 = mt5/IntradayMomentum.mq5.
set -e
cd "$(dirname "$0")"
mkdir -p build
git show 86af481:mt5/IntradayMomentum.mq5 > build/v200.mq5
git show 7c1fcc6:mt5/IntradayMomentum.mq5 > build/v201.mq5
git show e86a59d:mt5/IntradayMomentum.mq5 > build/v202.mq5
cp ../../../mt5/IntradayMomentum.mq5 build/v203.mq5
python3 prep_mq5.py build/v200.mq5 build/ea_v200.h EA_v200
python3 prep_mq5.py build/v201.mq5 build/ea_v201.h EA_v201
python3 prep_mq5.py build/v202.mq5 build/ea_v202.h EA_v202
python3 prep_mq5.py build/v203.mq5 build/ea_v203.h EA_v203
g++ -std=c++17 -O2 -Wall -Wno-unused-parameter -Wno-unused-variable -Wno-sign-compare -Ibuild -o build/driver driver.cpp
g++ -std=c++17 -O1 -w -Ibuild -o build/cal_check cal_check.cpp
[ -f build/bars_research.csv ] || python3 export_bars.py research build/bars_research.csv
[ -f build/bars_cfd.csv ] || python3 export_bars.py cfd build/bars_cfd.csv
echo "built: build/driver build/cal_check"
