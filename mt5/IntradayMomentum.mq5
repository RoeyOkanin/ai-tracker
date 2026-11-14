//+------------------------------------------------------------------+
//| IntradayMomentum.mq5                                             |
//| Nasdaq intraday momentum ("Beat the Market", Zarattini/Aziz/     |
//| Barbon) for FTMO US100.cash, same rules as the ai-tracker        |
//| backtest (scripts/prop/strategies.py::noise_momentum).           |
//|                                                                  |
//| Rules (all times New York, regular session 09:30-16:00):         |
//|  * Noise band: for every 5-min bar of the day, sigma = average   |
//|    over the last 14 sessions of |close(bar)/open(09:30) - 1|.    |
//|    Upper = max(today open, yesterday close) * (1 + sigma)        |
//|    Lower = min(today open, yesterday close) * (1 - sigma)        |
//|  * Decisions only when a 5-min bar closes on :00 or :30.         |
//|  * Exit check first: long exits if close < max(Upper, VWAP),     |
//|    short exits if close > min(Lower, VWAP).                      |
//|  * Entry (10:00..15:30 bar closes): close > Upper -> long,       |
//|    close < Lower -> short.                                       |
//|  * Everything flat at 15:59.                                     |
//|  * Size per day: DollarsPerPoint * (25000 / today open)          |
//|    * min(VolCap, VolTarget / std of last 14 daily returns)       |
//|    * buffer scale (funded mode only).                            |
//|  Safety (not in the backtest, rarely binds): server-side         |
//|  emergency stop and an equity guard below FTMO's daily loss.     |
//+------------------------------------------------------------------+
#property copyright "ai-tracker"
#property version   "1.00"

#include <Trade\Trade.mqh>

//--- sizing
input double InpDollarsPerPoint = 12.0;   // $ per index point at full size (challenge 12, funded 8)
input double InpVolTarget       = 0.012;  // daily vol target (1.2%)
input double InpVolCap          = 2.0;    // max vol multiplier
input bool   InpBufferScaling   = false;  // funded mode: shrink size as balance nears the max-loss floor
input double InpMinBufferScale  = 0.25;   // smallest buffer multiplier
//--- account / FTMO limits
input double InpInitialBalance  = 100000; // account starting balance
input double InpMaxLossPct      = 10.0;   // FTMO max loss % of initial (floor)
input double InpDailyGuardPct   = 4.5;    // close all + stop for the day if equity falls this % of initial below day-start balance
input double InpEmergencySLPct  = 4.5;    // server-side stop distance, as % of initial balance at this position size
//--- strategy
input int    InpLookback        = 14;     // noise lookback (sessions)
input double InpBandMult        = 1.0;    // band width multiplier
input int    InpExitHHMM        = 1559;   // NY time to flatten (HHMM)
//--- time zone (server -> New York)
input bool   InpAutoServerOffset   = true; // live: detect server UTC offset; tester: uses the manual values below
input int    InpServerWinterOffset = 2;    // server UTC offset in winter (FTMO MT5 is usually 2)
input bool   InpServerUsesEUDST    = true; // server adds +1h during EU summer time
//--- misc
input long   InpMagic           = 26111401;
input bool   InpLogCsv          = true;   // write decisions to MQL5/Files/IntradayMomentum_log.csv

CTrade trade;

//--- day state
int      g_dayKey        = 0;     // NY yyyymmdd of the prepared day
bool     g_dayReady      = false;
double   g_sigma[78];             // per 5-min slot from 09:30
double   g_prevClose     = 0.0;
double   g_dayOpen       = 0.0;
double   g_dayLots       = 0.0;
double   g_dayDpp        = 0.0;
bool     g_dayBlocked    = false; // daily guard hit
datetime g_lastBar       = 0;
int      g_serverDay     = -1;
double   g_dayStartBal   = 0.0;
int      g_winterOffset  = 2;
datetime g_lastPrepTry   = 0;

//+------------------------------------------------------------------+
//| calendar helpers                                                 |
//+------------------------------------------------------------------+
datetime MakeTime(int y, int mo, int d, int h = 0, int mi = 0)
  {
   MqlDateTime s;
   ZeroMemory(s);
   s.year = y; s.mon = mo; s.day = d; s.hour = h; s.min = mi; s.sec = 0;
   return StructToTime(s);
  }

int DowOf(datetime t) { MqlDateTime s; TimeToStruct(t, s); return s.day_of_week; }

// day of month of the n-th Sunday (n>=1)
int NthSunday(int y, int mo, int n)
  {
   int dow = DowOf(MakeTime(y, mo, 1));
   int first = 1 + (7 - dow) % 7;
   return first + 7 * (n - 1);
  }

int LastSunday(int y, int mo)
  {
   datetime nextFirst = (mo == 12) ? MakeTime(y + 1, 1, 1) : MakeTime(y, mo + 1, 1);
   datetime last = nextFirst - 86400;
   MqlDateTime s; TimeToStruct(last, s);
   return s.day - s.day_of_week;
  }

bool UsDst(datetime utc)
  {
   MqlDateTime s; TimeToStruct(utc, s);
   datetime start = MakeTime(s.year, 3, NthSunday(s.year, 3, 2), 7);   // 02:00 EST
   datetime end   = MakeTime(s.year, 11, NthSunday(s.year, 11, 1), 6); // 02:00 EDT
   return (utc >= start && utc < end);
  }

bool EuDst(datetime utc)
  {
   MqlDateTime s; TimeToStruct(utc, s);
   datetime start = MakeTime(s.year, 3, LastSunday(s.year, 3), 1);
   datetime end   = MakeTime(s.year, 10, LastSunday(s.year, 10), 1);
   return (utc >= start && utc < end);
  }

datetime ServerToUtc(datetime t)
  {
   datetime utc = t - g_winterOffset * 3600;
   int off = g_winterOffset + ((InpServerUsesEUDST && EuDst(utc)) ? 1 : 0);
   return t - off * 3600;
  }

datetime ServerToNy(datetime t)
  {
   datetime utc = ServerToUtc(t);
   return utc + (UsDst(utc) ? -4 : -5) * 3600;
  }

int DayKey(datetime ny) { MqlDateTime s; TimeToStruct(ny, s); return s.year * 10000 + s.mon * 100 + s.day; }
int MinOfDay(datetime ny) { MqlDateTime s; TimeToStruct(ny, s); return s.hour * 60 + s.min; }
int SlotOf(int minuteOfDay) { if(minuteOfDay < 570 || minuteOfDay >= 960) return -1; return (minuteOfDay - 570) / 5; }

//+------------------------------------------------------------------+
//| logging                                                          |
//+------------------------------------------------------------------+
void LogRow(string what, datetime ny, double price, double up, double lo, double vwap, double lots)
  {
   PrintFormat("[IMOM] %s %s px=%.2f up=%.2f lo=%.2f vwap=%.2f lots=%.2f",
               what, TimeToString(ny, TIME_DATE | TIME_MINUTES), price, up, lo, vwap, lots);
   if(!InpLogCsv) return;
   int h = FileOpen("IntradayMomentum_log.csv", FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_SHARE_READ, ',');
   if(h == INVALID_HANDLE) return;
   FileSeek(h, 0, SEEK_END);
   FileWrite(h, TimeToString(ny, TIME_DATE | TIME_MINUTES), what, DoubleToString(price, 2), DoubleToString(up, 2),
             DoubleToString(lo, 2), DoubleToString(vwap, 2), DoubleToString(lots, 2),
             DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2));
   FileClose(h);
  }

//+------------------------------------------------------------------+
//| position helpers                                                 |
//+------------------------------------------------------------------+
int CurrentSide()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      return (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
     }
   return 0;
  }

bool CloseAll(string why)
  {
   bool ok = true;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(!trade.PositionClose(tk))
        {
         PrintFormat("[IMOM] close failed (%s): %d %s", why, trade.ResultRetcode(), trade.ResultRetcodeDescription());
         ok = false;
        }
     }
   return ok;
  }

double MoneyPerPointPerLot()
  {
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tv <= 0 || ts <= 0) return 0;
   return tv / ts;
  }

double NormalizeLots(double lots)
  {
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step <= 0) step = 0.01;
   lots = MathFloor(lots / step) * step;
   if(lots < vmin) return 0.0;
   if(lots > vmax) lots = vmax;
   return NormalizeDouble(lots, 2);
  }

bool OpenPos(int side, double lots, string why)
  {
   // margin cap: Swing accounts have lower leverage; never use more than 80% of free margin
   double px = (side > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double margin = 0;
   if(OrderCalcMargin(side > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, _Symbol, lots, px, margin) && margin > 0)
     {
      double freeM = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      if(margin > 0.8 * freeM)
        {
         double cut = NormalizeLots(lots * 0.8 * freeM / margin);
         PrintFormat("[IMOM] margin cap: %.2f lots need %.2f margin, free %.2f -> %.2f lots", lots, margin, freeM, cut);
         lots = cut;
         if(lots <= 0) return false;
        }
     }
   double mpp = MoneyPerPointPerLot();
   double slDist = (mpp > 0 && lots > 0) ? InpEmergencySLPct / 100.0 * InpInitialBalance / (lots * mpp) : 0;
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   bool ok;
   if(side > 0)
     {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double sl = slDist > 0 ? NormalizeDouble(ask - slDist, digits) : 0;
      ok = trade.Buy(lots, _Symbol, 0, sl, 0, why);
     }
   else
     {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double sl = slDist > 0 ? NormalizeDouble(bid + slDist, digits) : 0;
      ok = trade.Sell(lots, _Symbol, 0, sl, 0, why);
     }
   if(!ok)
      PrintFormat("[IMOM] open failed: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
   return ok;
  }

//+------------------------------------------------------------------+
//| build noise band, prev close, vol and size for NY day `key`      |
//+------------------------------------------------------------------+
bool PrepareDay(int key)
  {
   g_dayReady = false;
   MqlRates r[];
   ArraySetAsSeries(r, false);
   datetime to = TimeTradeServer();
   int n = CopyRates(_Symbol, PERIOD_M5, to - 45 * 86400, to, r);
   if(n <= 0)
     {
      Print("[IMOM] no M5 history yet");
      return false;
     }
   // collect sessions (oldest first)
   int    keys[];
   double opens[], closes[];
   double slotClose[][78];
   int    nd = 0;
   ArrayResize(keys, 0); ArrayResize(opens, 0); ArrayResize(closes, 0); ArrayResize(slotClose, 0);
   for(int i = 0; i < n; i++)
     {
      datetime ny = ServerToNy(r[i].time);
      int slot = SlotOf(MinOfDay(ny));
      if(slot < 0) continue;
      int dk = DayKey(ny);
      if(dk >= key) continue;                       // only completed sessions before today
      if(nd == 0 || keys[nd - 1] != dk)
        {
         nd++;
         ArrayResize(keys, nd); ArrayResize(opens, nd); ArrayResize(closes, nd); ArrayResize(slotClose, nd);
         keys[nd - 1] = dk; opens[nd - 1] = 0; closes[nd - 1] = 0;
         for(int k = 0; k < 78; k++) slotClose[nd - 1][k] = -1;
        }
      if(slot == 0) opens[nd - 1] = r[i].open;
      slotClose[nd - 1][slot] = r[i].close;
      closes[nd - 1] = r[i].close;                  // last regular-session close
     }
   // keep sessions that have a 09:30 bar
   int valid[]; int nv = 0;
   ArrayResize(valid, 0);
   for(int d = 0; d < nd; d++)
      if(opens[d] > 0) { nv++; ArrayResize(valid, nv); valid[nv - 1] = d; }
   if(nv < InpLookback + 1)
     {
      PrintFormat("[IMOM] need %d sessions of M5 history, have %d. Scroll the M5 chart back to load more.", InpLookback + 1, nv);
      return false;
     }
   // sigma per slot over the last InpLookback sessions
   for(int k = 0; k < 78; k++)
     {
      double sum = 0; int cnt = 0;
      for(int j = nv - InpLookback; j < nv; j++)
        {
         int d = valid[j];
         if(slotClose[d][k] > 0) { sum += MathAbs(slotClose[d][k] / opens[d] - 1.0); cnt++; }
        }
      g_sigma[k] = (cnt > 0) ? sum / cnt * InpBandMult : -1;
     }
   g_prevClose = closes[valid[nv - 1]];
   // daily vol: sample std of the last 14 close-to-close returns
   double rets[]; int nr = 0;
   ArrayResize(rets, 0);
   for(int j = MathMax(1, nv - 14); j < nv; j++)
     {
      nr++; ArrayResize(rets, nr);
      rets[nr - 1] = closes[valid[j]] / closes[valid[j - 1]] - 1.0;
     }
   double mean = 0; for(int j = 0; j < nr; j++) mean += rets[j]; mean /= MathMax(1, nr);
   double var = 0; for(int j = 0; j < nr; j++) var += (rets[j] - mean) * (rets[j] - mean);
   double vol = (nr > 1) ? MathSqrt(var / (nr - 1)) : 0;
   if(vol <= 0) { Print("[IMOM] bad vol"); return false; }
   double volScale = MathMin(InpVolCap, InpVolTarget / vol);
   // buffer scale (funded)
   double bufScale = 1.0;
   if(InpBufferScaling)
     {
      double floorBal = InpInitialBalance * (1.0 - InpMaxLossPct / 100.0);
      double buf = (AccountInfoDouble(ACCOUNT_BALANCE) - floorBal) / (InpInitialBalance * InpMaxLossPct / 100.0);
      bufScale = MathMax(InpMinBufferScale, MathMin(1.0, buf));
     }
   g_dayKey = key;
   g_dayOpen = 0;
   g_dayDpp = InpDollarsPerPoint * volScale * bufScale;  // finalised with today's open in RefreshToday
   g_dayLots = 0;
   g_dayBlocked = false;
   g_dayReady = true;
   PrintFormat("[IMOM] day %d ready: prevClose=%.2f vol14=%.4f volScale=%.2f bufScale=%.2f sessions=%d",
               key, g_prevClose, vol, volScale, bufScale, nv);
   return true;
  }

//+------------------------------------------------------------------+
//| today's open and VWAP up to (and including) bar `upto`           |
//+------------------------------------------------------------------+
bool TodayStats(datetime upto, double &open, double &vwap, double &close)
  {
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, PERIOD_M5, upto - 8 * 3600, upto, r);
   if(n <= 0) return false;
   double pv = 0, v = 0; open = 0; close = 0;
   for(int i = 0; i < n; i++)
     {
      datetime ny = ServerToNy(r[i].time);
      if(DayKey(ny) != g_dayKey) continue;
      int slot = SlotOf(MinOfDay(ny));
      if(slot < 0) continue;
      if(slot == 0) open = r[i].open;
      double vol = (double)r[i].tick_volume;
      if(vol <= 0) vol = 1;
      pv += r[i].close * vol; v += vol;
      close = r[i].close;
     }
   if(open <= 0 || v <= 0) return false;
   vwap = pv / v;
   return true;
  }

//+------------------------------------------------------------------+
//| decision on a closed 5-min bar that ends on :00 / :30            |
//+------------------------------------------------------------------+
void OnCheckpoint(datetime barServer, datetime barNy)
  {
   int startMin = MinOfDay(barNy);
   int endMin = startMin + 5;
   int slot = SlotOf(startMin);
   if(slot < 0 || g_sigma[slot] < 0) return;

   double open, vwap, close;
   if(!TodayStats(barServer, open, vwap, close)) { Print("[IMOM] no 09:30 bar today, skipping"); return; }
   if(g_dayLots <= 0)
     {
      g_dayOpen = open;
      double dpp = g_dayDpp * 25000.0 / open;          // constant notional, as in the backtest
      double mpp = MoneyPerPointPerLot();
      g_dayLots = (mpp > 0) ? NormalizeLots(dpp / mpp) : 0;
      PrintFormat("[IMOM] today open=%.2f -> $%.2f/pt -> %.2f lots", open, dpp, g_dayLots);
     }
   double s = g_sigma[slot];
   double up = MathMax(open, g_prevClose) * (1.0 + s);
   double lo = MathMin(open, g_prevClose) * (1.0 - s);

   int side = CurrentSide();
   bool exitNow = false;
   if(side > 0 && close < MathMax(up, vwap)) exitNow = true;
   if(side < 0 && close > MathMin(lo, vwap)) exitNow = true;

   int want = 0;
   bool entryWindow = (endMin >= 600 && endMin <= 930);  // 10:00 .. 15:30 bar closes
   if(entryWindow && !g_dayBlocked)
     {
      if(close > up) want = 1;
      else if(close < lo) want = -1;
     }

   if(side != 0 && exitNow)
     {
      if(want == side)
        {
         LogRow("HOLD(exit+reenter)", barNy, close, up, lo, vwap, g_dayLots);
         return;                                       // backtest exits and re-enters on the same bar; holding is equivalent minus the spread
        }
      CloseAll("trail stop");
      LogRow(side > 0 ? "EXIT LONG" : "EXIT SHORT", barNy, close, up, lo, vwap, g_dayLots);
      side = 0;
     }
   if(side == 0 && want != 0 && g_dayLots > 0)
     {
      if(OpenPos(want, g_dayLots, want > 0 ? "IMOM long" : "IMOM short"))
         LogRow(want > 0 ? "BUY" : "SELL", barNy, close, up, lo, vwap, g_dayLots);
     }
   else if(side == 0)
      LogRow("FLAT", barNy, close, up, lo, vwap, g_dayLots);
  }

//+------------------------------------------------------------------+
void Heartbeat()
  {
   datetime srv = TimeTradeServer();
   // FTMO daily loss is measured from the balance at server midnight
   MqlDateTime sd; TimeToStruct(srv, sd);
   if(sd.day_of_year != g_serverDay)
     {
      g_serverDay = sd.day_of_year;
      g_dayStartBal = AccountInfoDouble(ACCOUNT_BALANCE);
     }
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double floorBal = InpInitialBalance * (1.0 - InpMaxLossPct / 100.0);
   if(eq <= g_dayStartBal - InpDailyGuardPct / 100.0 * InpInitialBalance || eq <= floorBal + 0.005 * InpInitialBalance)
     {
      if(CurrentSide() != 0)
        {
         CloseAll("equity guard");
         PrintFormat("[IMOM] EQUITY GUARD: equity %.2f, day start %.2f. Flat and done for today.", eq, g_dayStartBal);
        }
      g_dayBlocked = true;
     }

   datetime nyNow = ServerToNy(srv);
   int dow = DowOf(nyNow);
   if(dow == 0 || dow == 6) return;
   int key = DayKey(nyNow);
   int nowMin = MinOfDay(nyNow);

   if(key != g_dayKey && nowMin >= 570 && srv - g_lastPrepTry >= 60)
     {
      g_lastPrepTry = srv;
      PrepareDay(key);
     }
   if(!g_dayReady || g_dayKey != key) return;

   // end of day
   int exitMin = (InpExitHHMM / 100) * 60 + InpExitHHMM % 100;
   if(nowMin >= exitMin)
     {
      if(CurrentSide() != 0)
        {
         CloseAll("end of day");
         LogRow("EOD EXIT", nyNow, SymbolInfoDouble(_Symbol, SYMBOL_BID), 0, 0, 0, g_dayLots);
        }
      return;
     }

   // newest closed M5 bar
   datetime b1 = iTime(_Symbol, PERIOD_M5, 1);
   if(b1 == 0 || b1 == g_lastBar) return;
   g_lastBar = b1;
   datetime bNy = ServerToNy(b1);
   if(DayKey(bNy) != key) return;
   int endMin = MinOfDay(bNy) + 5;
   if(endMin % 30 != 0 || endMin < 600 || endMin > 960) return;
   OnCheckpoint(b1, bNy);
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(50);
   g_winterOffset = InpServerWinterOffset;
   bool tester = (bool)MQLInfoInteger(MQL_TESTER);
   if(InpAutoServerOffset && !tester)
     {
      long diff = (long)(TimeTradeServer() - TimeGMT());
      int cur = (int)MathRound(diff / 3600.0);
      g_winterOffset = cur - ((InpServerUsesEUDST && EuDst(TimeGMT())) ? 1 : 0);
     }
   datetime ny = ServerToNy(TimeTradeServer());
   PrintFormat("[IMOM] start: symbol=%s server winter offset=UTC%+d, New York now=%s, $/pt/lot=%.4f, magic=%I64d",
               _Symbol, g_winterOffset, TimeToString(ny, TIME_DATE | TIME_MINUTES), MoneyPerPointPerLot(), InpMagic);
   if(MoneyPerPointPerLot() <= 0) Print("[IMOM] WARNING: tick value unavailable, cannot size trades");
   g_dayStartBal = AccountInfoDouble(ACCOUNT_BALANCE);
   EventSetTimer(1);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason) { EventKillTimer(); }
void OnTimer() { Heartbeat(); }
void OnTick()  { Heartbeat(); }
//+------------------------------------------------------------------+
