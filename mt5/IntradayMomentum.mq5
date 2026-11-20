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
//|    * BelowMAMult if yesterday closed below its 50-day average    |
//|    * buffer scale (funded mode only).                            |
//|  * No new entries at 12:00 / 14:00; skip the day after a big win.|
//|  * Challenge: flat and done at the profit target (TargetPct),    |
//|    then one micro trade per day until the minimum trading days.  |
//|  Safety (not in the backtest, rarely binds): server-side         |
//|  emergency stop and an equity guard below FTMO's daily loss.     |
//|                                                                  |
//| v2.01 (2026-11-20): safety fixes only, trading rules unchanged.  |
//|  * NYSE calendar: no trading on US holidays (US100.cash still    |
//|    trades a futures-only morning until 13:00 NY) or early-close  |
//|    days (day after Thanksgiving, Dec 24, Jul 3: CFD stops 13:15  |
//|    NY). Holiday sessions are left out of the band/vol/MA history |
//|    (the backtest never had them).                                |
//|  * Anything still open outside the trading window is closed at   |
//|    the first tick (weekend, holiday, before 09:30, after 15:59). |
//|  * Failed closes back off (5 s .. 60 s), wait for the next tick  |
//|    after "market closed", and all requests are capped per day    |
//|    (FTMO forbids more than 2,000 server requests per day).       |
//|  * Daily-loss anchor = balance at 00:00 Prague time, saved in a  |
//|    terminal global variable: a restart cannot loosen the guard.  |
//|  * Profit target: closes are retried until flat, and the target  |
//|    only counts once the CLOSED balance is at/above it (FTMO).    |
//|  * A failed exit never opens the opposite side while the old     |
//|    position is still open (reversal taken if flat within 60 s).  |
//|  * Server-side stop never allows more than the room left to      |
//|    FTMO's daily and max-loss limits (backstop if VPS is down).   |
//|  * Waits for enough M5 history (MA50) before trading.            |
//|  * Refuses to run on a non-US100 chart.                          |
//| v2.02 (2026-11-20): robustness fixes, trading rules unchanged.   |
//|  * Inputs or chart changed: MT5 keeps the EA loaded (OnDeinit +  |
//|    OnInit only, globals keep their values). OnInit now resets    |
//|    all state, so new inputs apply at once, not the next day.     |
//|  * After a restart the M5 history may still be downloading: the  |
//|    day is prepared only once yesterday's session is complete     |
//|    (waits until 09:55, or 10 min after a restart; if it is still |
//|    missing then: exits only, no new entries, until it is there). |
//|  * A close that is only partly filled counts as failed: no       |
//|    reversal and no new entry while any position is still open.   |
//|  * Funded buffer scaling uses the balance before today's trades, |
//|    so a restart during the day does not change the size.         |
//+------------------------------------------------------------------+
#property copyright "ai-tracker"
#property version   "2.02"

#include <Trade\Trade.mqh>

//--- sizing
input double InpDollarsPerPoint = 10.0;   // $ per index point at full size (challenge 10, funded 8)
input double InpVolTarget       = 0.012;  // daily vol target (1.2%)
input double InpVolCap          = 1.0;    // max vol multiplier (1 = only scale DOWN in volatile markets; tested better than 2)
input bool   InpBufferScaling   = false;  // funded mode: shrink size as balance nears the max-loss floor
input double InpMinBufferScale  = 0.25;   // smallest buffer multiplier
//--- account / FTMO limits
input double InpInitialBalance  = 100000; // account starting balance
input double InpMaxLossPct      = 10.0;   // FTMO max loss % of initial (floor)
input double InpDailyGuardPct   = 4.5;    // close all + stop for the day if equity falls this % of initial below the FTMO day-start balance
input double InpEmergencySLPct  = 4.5;    // server-side stop distance, as % of initial balance at this position size
//--- strategy
input int    InpLookback        = 14;     // noise lookback (sessions)
input double InpBandMult        = 1.0;    // band width multiplier
input int    InpExitHHMM        = 1559;   // NY time to flatten (HHMM)
input string InpNoEntryTimes    = "1200,1400"; // NY bar-close times with no NEW entries (lunch chop, 14:00 releases); exits still run
input double InpSkipAfterWinPts = 167;    // skip the next day after a win > this many points at full size (167 x $10 = $1,670); 0 = off
input int    InpTrendMA         = 50;     // trend filter length in sessions (0 = off)
input double InpBelowMAMult     = 1.5;    // size multiplier when yesterday closed below the trend MA (momentum is stronger in falling markets)
//--- challenge
input double InpTargetPct       = 10.0;   // profit target % of initial: phase 1 = 10, phase 2 = 5, funded = 0 (off). At target: flat and stop
input int    InpMinTradingDays  = 4;      // FTMO minimum trading days: after the target, one micro trade per day until reached
input double InpTargetBufferPct = 0.10;   // close at target + this % of initial (slippage buffer: FTMO needs the CLOSED balance >= target)
//--- calendar / safety (v2.01)
input bool   InpUseUsCalendar     = true; // no trading on NYSE holidays and early-close days (day after Thanksgiving, Dec 24, Jul 3)
input string InpExtraClosedDays   = "";   // extra no-trade NY dates yyyymmdd, comma separated (unscheduled market closures)
input int    InpPreCloseLastEntry = 0;    // HHMM, 0 = off: no new entries after this NY time when the market then closes for > 2h (Fri, before Good Friday/Christmas/New Year)
input int    InpMaxRequestsPerDay = 1000; // hard cap on trade requests per NY day (FTMO forbids > 2,000 server requests per day)
input bool   InpCheckSymbol       = true; // refuse to run unless the chart symbol contains "US100"
//--- time zone (server -> New York)
input bool   InpAutoServerOffset   = true; // live: detect server UTC offset; tester: uses the manual values below
input int    InpServerWinterOffset = 2;    // server UTC offset in winter (FTMO MT5 is usually 2)
input int    InpServerDstRule      = 2;    // server summer time: 2 = US dates (FTMO, verified), 1 = EU dates, 0 = none
//--- misc
input long   InpMagic           = 26111401;
input bool   InpLogCsv          = true;   // write decisions to MQL5/Files/IntradayMomentum_log.csv

// trade server return codes used below (numeric, see ENUM_TRADE_RETURN_CODES)
#define RC_PLACED          10008
#define RC_DONE            10009
#define RC_DONE_PARTIAL    10010
#define RC_INVALID_VOLUME  10014
#define RC_INVALID_STOPS   10016
#define RC_TRADE_DISABLED  10017
#define RC_MARKET_CLOSED   10018
#define RC_NO_MONEY        10019
#define RC_CLIENT_NO_ALGO  10027
#define RC_NO_CONNECTION   10031
#define RC_LIMIT_VOLUME    10034

CTrade trade;

//--- day state
int      g_dayKey        = 0;     // NY yyyymmdd of the prepared day
bool     g_dayReady      = false;
double   g_sigma[78];             // per 5-min slot from 09:30
double   g_prevClose     = 0.0;
double   g_dayOpen       = 0.0;
double   g_dayLots       = 0.0;
double   g_dayDpp        = 0.0;
bool     g_dayBlocked    = false; // skip-after-win day
datetime g_lastBar       = 0;
int      g_winterOffset  = 2;
bool     g_offsetOk      = false; // server offset detected while connected
datetime g_lastPrepTry   = 0;
bool     g_targetDone    = false; // profit target reached (closed balance): no more normal trading
bool     g_targetClosing = false; // target hit, closing positions
//--- FTMO daily-loss anchor and guard (restart-proof)
int      g_anchorDay     = 0;     // Prague yyyymmdd of g_anchor
double   g_anchor        = 0.0;   // balance at 00:00 Prague time (FTMO: 00:00 CE(S)T)
int      g_guardDay      = 0;     // NY day on which the equity guard fired: no new entries that day
//--- order handling
bool     g_closePending  = false; // an exit failed: keep retrying, never open anything meanwhile
datetime g_closeFailAt   = 0;     // time of the last failed close (backoff)
int      g_closeFails    = 0;     // failed closes in a row
bool     g_waitTick      = false; // last close failed because the market is closed: retry on the next tick only
bool     g_inTick        = false;
int      g_reqDay        = 0;     // NY day of the request counter
int      g_reqCount      = 0;     // trade requests sent today
bool     g_reqWarned     = false;
int      g_pendSide      = 0;     // entry to retry after a transient failure
int      g_pendEndMin    = 0;
datetime g_pendUntil     = 0;
datetime g_lastOpenTry   = 0;
int      g_extraDays[];
int      g_noTradeLogDay = 0;
int      g_prepTryDay    = 0;     // NY day of the first PrepareDay attempt below
datetime g_prepFirstTry  = 0;     // first attempt to prepare that day (history wait limit)
bool     g_dayStale      = false; // day prepared with incomplete history: exits only, prepare again every minute

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

bool ServerDst(datetime utc)
  {
   if(InpServerDstRule == 2) return UsDst(utc);
   if(InpServerDstRule == 1) return EuDst(utc);
   return false;
  }

datetime ServerToUtc(datetime t)
  {
   datetime utc = t - g_winterOffset * 3600;
   int off = g_winterOffset + (ServerDst(utc) ? 1 : 0);
   return t - off * 3600;
  }

datetime UtcToServer(datetime utc) { return utc + (g_winterOffset + (ServerDst(utc) ? 1 : 0)) * 3600; }

datetime ServerToNy(datetime t)
  {
   datetime utc = ServerToUtc(t);
   return utc + (UsDst(utc) ? -4 : -5) * 3600;
  }

int DayKey(datetime ny) { MqlDateTime s; TimeToStruct(ny, s); return s.year * 10000 + s.mon * 100 + s.day; }
int MinOfDay(datetime ny) { MqlDateTime s; TimeToStruct(ny, s); return s.hour * 60 + s.min; }
int SlotOf(int minuteOfDay) { if(minuteOfDay < 570 || minuteOfDay >= 960) return -1; return (minuteOfDay - 570) / 5; }

// FTMO resets the daily loss at 00:00 CE(S)T (Prague: UTC+1, UTC+2 in EU summer time)
int PragueDayKey(datetime srv)
  {
   datetime utc = ServerToUtc(srv);
   return DayKey(utc + (EuDst(utc) ? 2 : 1) * 3600);
  }

//+------------------------------------------------------------------+
//| NYSE calendar (rules checked against 2016-2026 QQQ sessions)     |
//+------------------------------------------------------------------+
datetime KeyToTime(int key) { return MakeTime(key / 10000, (key / 100) % 100, key % 100); }
int DowYmd(int y, int mo, int d) { return DowOf(MakeTime(y, mo, d)); }
int DaysInMonth(int y, int mo)
  {
   datetime a = MakeTime(y, mo, 1);
   datetime b = (mo == 12) ? MakeTime(y + 1, 1, 1) : MakeTime(y, mo + 1, 1);
   return (int)((b - a) / 86400);
  }
// day of month of the n-th weekday wd (0 = Sunday .. 6 = Saturday)
int NthWeekday(int y, int mo, int wd, int n) { return 1 + (wd - DowYmd(y, mo, 1) + 7) % 7 + 7 * (n - 1); }
int LastWeekday(int y, int mo, int wd) { int last = DaysInMonth(y, mo); return last - (DowYmd(y, mo, last) - wd + 7) % 7; }
// fixed-date holiday moved to Friday (Saturday) or Monday (Sunday)
int ObservedKey(int y, int mo, int d)
  {
   datetime t = MakeTime(y, mo, d);
   int w = DowOf(t);
   if(w == 6) t -= 86400;
   else if(w == 0) t += 86400;
   return DayKey(t);
  }
int GoodFridayKey(int y)
  {
   int a = y % 19, b = y / 100, c = y % 100, d = b / 4, e = b % 4, f = (b + 8) / 25, g = (b - f + 1) / 3;
   int h = (19 * a + b - d - g + 15) % 30, i = c / 4, k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7;
   int m = (a + 11 * h + 22 * l) / 451;
   int mo = (h + l - 7 * m + 114) / 31, da = ((h + l - 7 * m + 114) % 31) + 1;
   return DayKey(MakeTime(y, mo, da) - 2 * 86400);
  }
bool IsNyseHoliday(int key)
  {
   int y = key / 10000;
   int w1 = DowYmd(y, 1, 1);
   if(w1 != 6 && key == (w1 == 0 ? y * 10000 + 102 : y * 10000 + 101)) return true; // New Year (no holiday when Jan 1 is a Saturday)
   if(key == y * 10000 + 100 + NthWeekday(y, 1, 1, 3)) return true;               // Martin Luther King Jr. Day
   if(key == y * 10000 + 200 + NthWeekday(y, 2, 1, 3)) return true;               // Washington's Birthday
   if(key == GoodFridayKey(y)) return true;                                       // Good Friday
   if(key == y * 10000 + 500 + LastWeekday(y, 5, 1)) return true;                 // Memorial Day
   if(y >= 2022 && key == ObservedKey(y, 6, 19)) return true;                     // Juneteenth
   if(key == ObservedKey(y, 7, 4)) return true;                                   // Independence Day
   if(key == y * 10000 + 900 + NthWeekday(y, 9, 1, 1)) return true;               // Labor Day
   if(key == y * 10000 + 1100 + NthWeekday(y, 11, 4, 4)) return true;             // Thanksgiving
   if(key == ObservedKey(y, 12, 25)) return true;                                 // Christmas
   return false;
  }
// NYSE closes 13:00 NY (US100.cash 13:15): day after Thanksgiving, Dec 24 and Jul 3 when Mon-Thu
bool IsEarlyClose(int key)
  {
   int y = key / 10000;
   if(key == y * 10000 + 1100 + NthWeekday(y, 11, 4, 4) + 1) return true;
   int w = DowYmd(y, 12, 24);
   if(key == y * 10000 + 1224 && w >= 1 && w <= 4) return true;
   w = DowYmd(y, 7, 3);
   if(key == y * 10000 + 703 && w >= 1 && w <= 4) return true;
   return false;
  }
bool IsExtraClosed(int key)
  {
   for(int i = 0; i < ArraySize(g_extraDays); i++)
      if(g_extraDays[i] == key) return true;
   return false;
  }
// no trading at all that day (CME closed too): weekend, New Year, Good Friday, Christmas
bool IsFullClosure(int key)
  {
   int y = key / 10000;
   int w = DowOf(KeyToTime(key));
   if(w == 0 || w == 6) return true;
   if(key == y * 10000 + 101 || (DowYmd(y, 1, 1) == 0 && key == y * 10000 + 102)) return true;
   if(key == GoodFridayKey(y)) return true;
   if(key == ObservedKey(y, 12, 25)) return true;
   return false;
  }
// 0 = no trading (weekend, holiday, extra closed day), 1 = regular session, 2 = early close
int DayType(int key)
  {
   int w = DowOf(KeyToTime(key));
   if(w == 0 || w == 6) return 0;
   if(IsExtraClosed(key)) return 0;
   if(!InpUseUsCalendar) return 1;
   if(IsNyseHoliday(key)) return 0;
   if(IsEarlyClose(key)) return 2;
   return 1;
  }
int NextDayKey(int key) { return DayKey(KeyToTime(key) + 86400); }
// previous NYSE session day (not a weekend, NYSE holiday or extra closed day)
int PrevSessionKey(int key)
  {
   int k = key;
   for(int i = 0; i < 14; i++)
     {
      k = DayKey(KeyToTime(k) - 86400);
      int w = DowOf(KeyToTime(k));
      if(w != 0 && w != 6 && !IsNyseHoliday(k) && !IsExtraClosed(k)) return k;
     }
   return 0;
  }

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
//| terminal global variables (survive restarts), per account        |
//+------------------------------------------------------------------+
string GvName(string what)
  {
   return "IMOM_" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + "_" + IntegerToString(InpMagic) + "_" + what;
  }

void GvSave(string what, double v)
  {
   GlobalVariableSet(GvName(what), v);
   GlobalVariablesFlush();
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

// FTMO forbids > 2,000 server requests per day: every trade request goes through this budget
bool ReqBudget()
  {
   if(g_reqCount < InpMaxRequestsPerDay) return true;
   if(!g_reqWarned)
     {
      PrintFormat("[IMOM] STOP: %d trade requests today (cap %d). No more requests until the next NY day.", g_reqCount, InpMaxRequestsPerDay);
      g_reqWarned = true;
     }
   return false;
  }

// rejected by the terminal itself (Algo Trading off / offline): never reaches the server
bool ClientSideReject(uint rc) { return rc == RC_CLIENT_NO_ALGO || rc == RC_NO_CONNECTION; }

// wait after the n-th failed close in a row: 5, 10, 20, 40, then 60 s
int CloseRetryDelay()
  {
   int d = 5;
   for(int i = 1; i < g_closeFails && d < 60; i++) d *= 2;
   return MathMin(d, 60);
  }

// close every position of this EA; true only if all closes went through.
// Failed closes back off (5 s .. 60 s), and after "market closed" wait for the next tick.
bool CloseAllSafe(string why)
  {
   datetime now = TimeTradeServer();
   if(g_waitTick && !g_inTick) return false;
   if(g_closeFails > 0 && now - g_closeFailAt < CloseRetryDelay()) return false;
   bool ok = true;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(!ReqBudget()) { ok = false; break; }
      g_reqCount++;
      if(!trade.PositionClose(tk))
        {
         uint rc = trade.ResultRetcode();
         if(ClientSideReject(rc)) g_reqCount--;
         PrintFormat("[IMOM] close failed (%s): %u %s", why, rc, trade.ResultRetcodeDescription());
         if(rc == RC_MARKET_CLOSED || rc == RC_TRADE_DISABLED || rc == RC_NO_CONNECTION || rc == RC_CLIENT_NO_ALGO)
            g_waitTick = true;
         ok = false;
        }
     }
   if(ok) { g_waitTick = false; g_closeFails = 0; g_closeFailAt = 0; }
   else { g_closeFails++; g_closeFailAt = now; }
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
   lots = MathFloor(lots / step + 1e-9) * step;
   if(lots < vmin) return 0.0;
   if(lots > vmax) lots = vmax;
   return NormalizeDouble(lots, 2);
  }

// 1 = opened, 0 = transient failure (retry), -1 = do not retry
int OpenPos(int side, double lots, string why)
  {
   if(CurrentSide() != 0)                                 // never two positions (a partly filled close leaves one open)
     {
      Print("[IMOM] a position is still open: no new entry");
      return -1;
     }
   if(!ReqBudget()) return -1;
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
         if(lots <= 0) return -1;
        }
     }
   // server-side stop: 4.5% of initial at this size, but never more than the room left to FTMO's
   // daily limit (guard + 0.25%) or the max-loss floor (+0.25%). Only matters if the EA is not running.
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double floorBal = InpInitialBalance * (1.0 - InpMaxLossPct / 100.0);
   double room = InpEmergencySLPct / 100.0 * InpInitialBalance;
   room = MathMin(room, eq - (g_anchor - (InpDailyGuardPct + 0.25) / 100.0 * InpInitialBalance));
   room = MathMin(room, eq - (floorBal + 0.0025 * InpInitialBalance));
   if(room <= 0)
     {
      PrintFormat("[IMOM] no room left to FTMO limits (equity %.2f, day start %.2f): no entry", eq, g_anchor);
      return -1;
     }
   double mpp = MoneyPerPointPerLot();
   double slDist = (mpp > 0 && lots > 0) ? room / (lots * mpp) : 0;
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   bool ok;
   g_lastOpenTry = TimeTradeServer();
   g_reqCount++;
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
   uint rc = trade.ResultRetcode();
   if(ok && (rc == RC_DONE || rc == RC_PLACED || rc == RC_DONE_PARTIAL)) return 1;
   if(ClientSideReject(rc)) g_reqCount--;
   PrintFormat("[IMOM] open failed: %u %s", rc, trade.ResultRetcodeDescription());
   if(rc == RC_NO_MONEY || rc == RC_INVALID_VOLUME || rc == RC_INVALID_STOPS || rc == RC_TRADE_DISABLED ||
      rc == RC_MARKET_CLOSED || rc == RC_LIMIT_VOLUME || rc == RC_CLIENT_NO_ALGO)
      return -1;
   return 0;
  }

//+------------------------------------------------------------------+
//| true if NY minute-of-day `m` is listed in InpNoEntryTimes        |
//+------------------------------------------------------------------+
bool NoEntryAt(int m)
  {
   string parts[];
   int n = StringSplit(InpNoEntryTimes, ',', parts);
   for(int i = 0; i < n; i++)
     {
      string t = parts[i];
      StringTrimLeft(t); StringTrimRight(t);
      if(StringLen(t) == 0) continue;
      int v = (int)StringToInteger(t);
      if((v / 100) * 60 + v % 100 == m) return true;
     }
   return false;
  }

// may a NEW position be opened on NY day `key` at bar-close minute `endMin`?
bool EntriesAllowed(int key, int endMin)
  {
   if(g_dayBlocked || g_guardDay == key || g_targetClosing || g_closePending || g_dayStale) return false;
   if(DayType(key) != 1) return false;
   if(InpPreCloseLastEntry > 0 && IsFullClosure(NextDayKey(key)))
     {
      int cut = (InpPreCloseLastEntry / 100) * 60 + InpPreCloseLastEntry % 100;
      if(endMin > cut) return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
//| FTMO trading days: distinct NY days with an entry by this EA     |
//+------------------------------------------------------------------+
int TradedDays(bool &today)
  {
   today = false;
   if(!HistorySelect(0, TimeTradeServer() + 86400)) return 0;
   int keys[]; int nk = 0;
   ArrayResize(keys, 0);
   int n = HistoryDealsTotal();
   for(int i = 0; i < n; i++)
     {
      ulong tk = HistoryDealGetTicket(i);
      if(tk == 0) continue;
      if(HistoryDealGetInteger(tk, DEAL_MAGIC) != InpMagic) continue;
      if(HistoryDealGetInteger(tk, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
      int k = DayKey(ServerToNy((datetime)HistoryDealGetInteger(tk, DEAL_TIME)));
      if(k == g_dayKey) today = true;
      bool seen = false;
      for(int j = 0; j < nk; j++) if(keys[j] == k) { seen = true; break; }
      if(!seen) { nk++; ArrayResize(keys, nk); keys[nk - 1] = k; }
     }
   return nk;
  }

//+------------------------------------------------------------------+
//| this EA's net P&L on NY day `dayKey` (closed deals)              |
//+------------------------------------------------------------------+
double DayPnl(int dayKey)
  {
   datetime now = TimeTradeServer();
   if(!HistorySelect(now - 10 * 86400, now + 60)) return 0;
   double sum = 0;
   int n = HistoryDealsTotal();
   for(int i = 0; i < n; i++)
     {
      ulong tk = HistoryDealGetTicket(i);
      if(tk == 0) continue;
      if(HistoryDealGetInteger(tk, DEAL_MAGIC) != InpMagic) continue;
      if(HistoryDealGetString(tk, DEAL_SYMBOL) != _Symbol) continue;
      datetime t = (datetime)HistoryDealGetInteger(tk, DEAL_TIME);
      if(DayKey(ServerToNy(t)) != dayKey) continue;
      sum += HistoryDealGetDouble(tk, DEAL_PROFIT) + HistoryDealGetDouble(tk, DEAL_COMMISSION) + HistoryDealGetDouble(tk, DEAL_SWAP);
     }
   return sum;
  }

//+------------------------------------------------------------------+
//| FTMO day-start balance: saved at the Prague day change, restored |
//| after a restart; first run of a day rebuilds it from history     |
//+------------------------------------------------------------------+
double BalanceAtPragueMidnight(datetime srv)
  {
   datetime utc = ServerToUtc(srv);
   int off = EuDst(utc) ? 2 : 1;
   long loc = (long)utc + off * 3600;
   datetime midUtc = (datetime)(loc - loc % 86400 - off * 3600);
   datetime from = UtcToServer(midUtc);
   double sum = 0;
   if(HistorySelect(from, srv + 3600))
     {
      int n = HistoryDealsTotal();
      for(int i = 0; i < n; i++)
        {
         ulong tk = HistoryDealGetTicket(i);
         if(tk == 0) continue;
         long type = HistoryDealGetInteger(tk, DEAL_TYPE);
         if(type != DEAL_TYPE_BUY && type != DEAL_TYPE_SELL) continue;
         if((datetime)HistoryDealGetInteger(tk, DEAL_TIME) < from) continue;
         sum += HistoryDealGetDouble(tk, DEAL_PROFIT) + HistoryDealGetDouble(tk, DEAL_COMMISSION) + HistoryDealGetDouble(tk, DEAL_SWAP);
        }
     }
   return AccountInfoDouble(ACCOUNT_BALANCE) - sum;
  }

void UpdateAnchor()
  {
   int pk = PragueDayKey(TimeTradeServer());
   if(pk == g_anchorDay) return;
   string nd = GvName("anchorday"), nv = GvName("anchor");
   if(GlobalVariableCheck(nd) && GlobalVariableCheck(nv) && (int)GlobalVariableGet(nd) == pk)
     {
      g_anchor = GlobalVariableGet(nv);
      PrintFormat("[IMOM] FTMO day %d: start balance %.2f (restored after restart)", pk, g_anchor);
     }
   else
     {
      g_anchor = BalanceAtPragueMidnight(TimeTradeServer());
      GvSave("anchor", g_anchor);
      GvSave("anchorday", pk);
      PrintFormat("[IMOM] FTMO day %d: start balance %.2f", pk, g_anchor);
     }
   g_anchorDay = pk;
  }

//+------------------------------------------------------------------+
//| server UTC offset (only trusted while connected)                 |
//+------------------------------------------------------------------+
void DetectOffset()
  {
   if(!TerminalInfoInteger(TERMINAL_CONNECTED)) return;
   long diff = (long)(TimeTradeServer() - TimeGMT());
   int cur = (int)MathRound(diff / 3600.0);
   int w = cur - (ServerDst(TimeGMT()) ? 1 : 0);
   if(w < -12 || w > 14) return;
   if(w != InpServerWinterOffset)
      PrintFormat("[IMOM] WARNING: server winter offset detected UTC%+d, expected UTC%+d. Check the New York time printed below.", w, InpServerWinterOffset);
   g_winterOffset = w;
   g_offsetOk = true;
  }

//+------------------------------------------------------------------+
//| build noise band, prev close, vol and size for NY day `key`      |
//+------------------------------------------------------------------+
bool PrepareDay(int key, int nowMin)
  {
   bool redo = (g_dayKey == key && g_dayStale);   // preparing today again because the history was incomplete
   g_dayReady = false;
   MqlRates r[];
   ArraySetAsSeries(r, false);
   datetime to = TimeTradeServer();
   int days = (InpTrendMA > 0) ? MathMax(45, (int)MathCeil(InpTrendMA * 1.6) + 15) : 45;
   int n = CopyRates(_Symbol, PERIOD_M5, to - days * 86400, to, r);
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
      if(IsExtraClosed(dk)) continue;
      if(InpUseUsCalendar && IsNyseHoliday(dk)) continue; // futures-only holiday morning: not a session in the backtest
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
   // after a restart the terminal may still be downloading history: yesterday's session must be
   // there and complete (up to its last bar), otherwise wait until 09:55 or 10 min after a restart
   int lastD = valid[nv - 1];
   int expPrev = PrevSessionKey(key);
   int lastSlot = IsEarlyClose(keys[lastD]) ? 41 : 77;            // early close: last NYSE bar 12:55
   bool complete = (keys[lastD] == expPrev && slotClose[lastD][lastSlot] > 0);
   if(!complete)
     {
      if(nowMin < 595 || TimeTradeServer() - g_prepFirstTry < 600)
        {
         PrintFormat("[IMOM] waiting for M5 history: last session %d (complete=%s), expected %d (retry every minute)",
                     keys[lastD], slotClose[lastD][lastSlot] > 0 ? "yes" : "no", expPrev);
         return false;
        }
      if(!redo)
         PrintFormat("[IMOM] WARNING: M5 history still incomplete (last session %d, expected %d): exits only, no new entries until it is complete (checked every minute)",
                     keys[lastD], expPrev);
     }
   bool talk = (!redo || complete);                // no repeated log lines while preparing again
   if(InpTrendMA > 0 && InpBelowMAMult != 1.0 && nv < InpTrendMA && nowMin < 595)
     {
      PrintFormat("[IMOM] waiting for M5 history: %d sessions, MA%d needs %d (retry every minute until 09:55)", nv, InpTrendMA, InpTrendMA);
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
      double bal0 = AccountInfoDouble(ACCOUNT_BALANCE) - DayPnl(key);   // balance before today's trades: same after a restart
      double buf = (bal0 - floorBal) / (InpInitialBalance * InpMaxLossPct / 100.0);
      bufScale = MathMax(InpMinBufferScale, MathMin(1.0, buf));
     }
   // trend tilt: intraday momentum is stronger when the market is below its trend average
   // (tested 2016-21 and 2022-26 separately, MA 20..200 and x1.25..x1.5 all help)
   double tilt = 1.0;
   if(InpTrendMA > 0 && InpBelowMAMult != 1.0)
     {
      if(nv >= InpTrendMA)
        {
         double sm = 0;
         for(int j = nv - InpTrendMA; j < nv; j++) sm += closes[valid[j]];
         double ma = sm / InpTrendMA;
         if(closes[valid[nv - 1]] < ma) tilt = InpBelowMAMult;
         if(talk) PrintFormat("[IMOM] trend: close %.2f vs MA%d %.2f -> x%.2f", closes[valid[nv - 1]], InpTrendMA, ma, tilt);
        }
      else
         PrintFormat("[IMOM] WARNING: trend MA%d needs %d sessions, have %d: no tilt today (scroll the M5 chart back to load more)", InpTrendMA, InpTrendMA, nv);
     }
   g_dayKey = key;
   g_dayOpen = 0;
   g_dayDpp = InpDollarsPerPoint * volScale * bufScale * tilt;  // finalised with today's open
   g_dayLots = 0;
   g_dayBlocked = false;
   g_pendSide = 0;
   // after a big trend-day win the next day tends to chop (tested 2016-2026, both halves): sit it out
   if(InpSkipAfterWinPts > 0)
     {
      double yPnl = DayPnl(keys[valid[nv - 1]]);
      double th = InpSkipAfterWinPts * InpDollarsPerPoint * bufScale;
      if(yPnl > th)
        {
         g_dayBlocked = true;
         if(talk) PrintFormat("[IMOM] yesterday won $%.2f > $%.2f: no new trades today", yPnl, th);
        }
     }
   g_dayStale = !complete;
   g_dayReady = true;
   if(talk) PrintFormat("[IMOM] day %d ready: prevClose=%.2f vol14=%.4f volScale=%.2f bufScale=%.2f tilt=%.2f sessions=%d",
               key, g_prevClose, vol, volScale, bufScale, tilt, nv);
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
   if(g_targetClosing) return;

   if(g_targetDone)
     {
      if(CurrentSide() != 0)
        {
         if(CloseAllSafe("target done"))
            LogRow("MICRO CLOSE", barNy, SymbolInfoDouble(_Symbol, SYMBOL_BID), 0, 0, 0, 0);
         return;
        }
      bool today = false;
      int td = TradedDays(today);
      if(td < InpMinTradingDays && !today && DayType(g_dayKey) == 1 && ReqBudget())
        {
         double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
         g_reqCount++;
         if(trade.Buy(vmin, _Symbol, 0, 0, 0, "IMOM min-days"))
            LogRow("MICRO OPEN (min trading days)", barNy, SymbolInfoDouble(_Symbol, SYMBOL_ASK), 0, 0, 0, vmin);
        }
      return;
     }
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
   if(entryWindow && NoEntryAt(endMin)) entryWindow = false;
   if(entryWindow && EntriesAllowed(g_dayKey, endMin))
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
      if(!CloseAllSafe("trail stop") || CurrentSide() != 0)   // rejected, or only partly filled
        {
         g_closePending = true;                        // retried with backoff; nothing new opens until it is flat
         if(want != 0 && want != side)                 // reversal: take the new side only if flat within 60 s
           { g_pendSide = want; g_pendEndMin = endMin; g_pendUntil = TimeTradeServer() + 60; }
         LogRow("EXIT PENDING, retrying", barNy, close, up, lo, vwap, g_dayLots);
         return;
        }
      LogRow(side > 0 ? "EXIT LONG" : "EXIT SHORT", barNy, close, up, lo, vwap, g_dayLots);
      side = 0;
     }
   if(side == 0 && want != 0 && g_dayLots > 0)
     {
      int rc = OpenPos(want, g_dayLots, want > 0 ? "IMOM long" : "IMOM short");
      if(rc == 1)
         LogRow(want > 0 ? "BUY" : "SELL", barNy, close, up, lo, vwap, g_dayLots);
      else if(rc == 0)
        {
         g_pendSide = want; g_pendEndMin = endMin; g_pendUntil = TimeTradeServer() + 60;   // transient: retry for 60 s
        }
     }
   else if(side == 0)
      LogRow("FLAT", barNy, close, up, lo, vwap, g_dayLots);
  }

//+------------------------------------------------------------------+
void Heartbeat()
  {
   if(InpAutoServerOffset && !g_offsetOk && !(bool)MQLInfoInteger(MQL_TESTER)) DetectOffset();
   datetime srv = TimeTradeServer();
   datetime nyNow = ServerToNy(srv);
   int key = DayKey(nyNow);
   int nowMin = MinOfDay(nyNow);
   if(key != g_reqDay) { g_reqDay = key; g_reqCount = 0; g_reqWarned = false; }
   UpdateAnchor();

   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   int side = CurrentSide();
   if(side == 0) { g_waitTick = false; g_closeFails = 0; }

   // profit target: FTMO counts the balance with all positions closed
   if(InpTargetPct > 0 && !g_targetDone)
     {
      double tgt = InpInitialBalance * (1.0 + InpTargetPct / 100.0);
      double bal = AccountInfoDouble(ACCOUNT_BALANCE);
      // closed balance already at target with a position open only happens after a restart (micro trade)
      if(!g_targetClosing && side != 0 && (eq >= tgt + InpTargetBufferPct / 100.0 * InpInitialBalance || bal >= tgt))
        {
         g_targetClosing = true;
         PrintFormat("[IMOM] PROFIT TARGET %.1f%% hit: equity %.2f, balance %.2f, closing all", InpTargetPct, eq, bal);
        }
      if(g_targetClosing && side != 0) CloseAllSafe("profit target");
      side = CurrentSide();
      bal = AccountInfoDouble(ACCOUNT_BALANCE);
      if(side == 0 && (g_targetClosing || bal >= tgt))
        {
         g_targetClosing = false;
         if(bal >= tgt)
           {
            g_targetDone = true;
            PrintFormat("[IMOM] PROFIT TARGET DONE: closed balance %.2f >= %.2f. Normal trading stopped (micro trades only until %d trading days).",
                        bal, tgt, InpMinTradingDays);
           }
         else
            PrintFormat("[IMOM] target close slipped: balance %.2f < %.2f, normal trading continues", bal, tgt);
        }
     }

   // equity guard: FTMO daily limit (day-start balance - 5%) and max-loss floor
   double floorBal = InpInitialBalance * (1.0 - InpMaxLossPct / 100.0);
   if(eq <= g_anchor - InpDailyGuardPct / 100.0 * InpInitialBalance || eq <= floorBal + 0.005 * InpInitialBalance)
     {
      if(g_guardDay != key)
        {
         PrintFormat("[IMOM] EQUITY GUARD: equity %.2f, FTMO day start %.2f. Flat and no new entries today.", eq, g_anchor);
         g_guardDay = key;
         GvSave("guardday", key);
        }
      if(side != 0) CloseAllSafe("equity guard");
     }

   // outside the trading window nothing may stay open (weekend, holiday, before 09:30, after the exit time)
   int dtype = DayType(key);
   int exitMin = (InpExitHHMM / 100) * 60 + InpExitHHMM % 100;
   int closeMin = (dtype == 2) ? 12 * 60 + 45 : exitMin;   // early-close day: CFD stops 13:15 NY
   if(dtype == 0 || nowMin < 570 || nowMin >= closeMin)
     {
      if(CurrentSide() != 0 && CloseAllSafe(dtype == 0 ? "market closed day" : "end of day"))
         LogRow("EOD EXIT", nyNow, SymbolInfoDouble(_Symbol, SYMBOL_BID), 0, 0, 0, g_dayLots);
      if(CurrentSide() == 0) { g_closePending = false; g_pendSide = 0; }
      return;
     }
   if(dtype == 2 && g_noTradeLogDay != key)
     {
      g_noTradeLogDay = key;
      PrintFormat("[IMOM] %d is a US early-close day (13:00): no trading today", key);
     }

   if(key != g_dayKey)
     {
      if(srv - g_lastPrepTry < 60) return;
      g_lastPrepTry = srv;
      if(g_prepTryDay != key) { g_prepTryDay = key; g_prepFirstTry = srv; }
      if(InpAutoServerOffset && !(bool)MQLInfoInteger(MQL_TESTER)) DetectOffset();
      if(!PrepareDay(key, nowMin)) return;
     }
   else if(g_dayStale && srv - g_lastPrepTry >= 60)
     {
      g_lastPrepTry = srv;
      if(!PrepareDay(key, nowMin)) g_dayReady = true;   // keep trading on the current day state if it fails
     }
   if(!g_dayReady) return;

   // a failed exit is retried before anything else
   if(g_closePending)
     {
      if(CurrentSide() != 0) CloseAllSafe("exit retry");
      if(CurrentSide() != 0) return;
      g_closePending = false;
      LogRow("EXIT (retry ok)", nyNow, SymbolInfoDouble(_Symbol, SYMBOL_BID), 0, 0, 0, g_dayLots);
     }
   // an entry that failed for a transient reason is retried for up to 60 s
   if(g_pendSide != 0)
     {
      if(srv > g_pendUntil || CurrentSide() != 0 || !EntriesAllowed(key, g_pendEndMin)) g_pendSide = 0;
      else if(srv - g_lastOpenTry >= 10)
        {
         int rc = OpenPos(g_pendSide, g_dayLots, g_pendSide > 0 ? "IMOM long retry" : "IMOM short retry");
         if(rc == 1) LogRow(g_pendSide > 0 ? "BUY (retry)" : "SELL (retry)", nyNow, SymbolInfoDouble(_Symbol, SYMBOL_BID), 0, 0, 0, g_dayLots);
         if(rc != 0) g_pendSide = 0;
        }
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
//| MT5 does not reload an EA when its inputs or the chart change:   |
//| OnDeinit + OnInit run and global variables keep their values.    |
//| Start every OnInit from a clean state, as after a fresh load.    |
//+------------------------------------------------------------------+
void ResetState()
  {
   g_dayKey = 0; g_dayReady = false; g_prevClose = 0; g_dayOpen = 0; g_dayLots = 0; g_dayDpp = 0; g_dayBlocked = false;
   for(int k = 0; k < 78; k++) g_sigma[k] = -1;
   g_lastBar = 0; g_offsetOk = false; g_lastPrepTry = 0; g_prepTryDay = 0; g_prepFirstTry = 0; g_dayStale = false;
   g_targetDone = false; g_targetClosing = false;               // restored from the closed balance
   g_anchorDay = 0; g_anchor = 0; g_guardDay = 0;               // restored from terminal global variables
   g_closePending = false; g_closeFailAt = 0; g_closeFails = 0; g_waitTick = false; g_inTick = false;
   g_pendSide = 0; g_pendEndMin = 0; g_pendUntil = 0; g_lastOpenTry = 0;
   g_noTradeLogDay = 0;
   // g_reqDay / g_reqCount are kept: requests already sent today still count
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpCheckSymbol && StringFind(_Symbol, "US100") < 0)
     {
      PrintFormat("[IMOM] wrong chart: %s. Attach this EA to the US100.cash chart.", _Symbol);
      return INIT_FAILED;
     }
   ResetState();
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(50);
   g_winterOffset = InpServerWinterOffset;
   bool tester = (bool)MQLInfoInteger(MQL_TESTER);
   if(InpAutoServerOffset && !tester) DetectOffset();
   // extra closed days
   string parts[];
   int n = StringSplit(InpExtraClosedDays, ',', parts);
   ArrayResize(g_extraDays, 0);
   for(int i = 0; i < n; i++)
     {
      string t = parts[i];
      StringTrimLeft(t); StringTrimRight(t);
      if(StringLen(t) != 8) continue;
      int k = ArraySize(g_extraDays);
      ArrayResize(g_extraDays, k + 1);
      g_extraDays[k] = (int)StringToInteger(t);
     }
   // state that must survive a restart
   if(GlobalVariableCheck(GvName("guardday"))) g_guardDay = (int)GlobalVariableGet(GvName("guardday"));
   UpdateAnchor();
   // warm up the M5 history (MA50 needs ~75 calendar days)
   MqlRates warm[];
   CopyRates(_Symbol, PERIOD_M5, TimeTradeServer() - 120 * 86400, TimeTradeServer(), warm);

   datetime ny = ServerToNy(TimeTradeServer());
   PrintFormat("[IMOM] v2.02 start: symbol=%s server winter offset=UTC%+d%s, New York now=%s, $/pt/lot=%.4f, magic=%I64d",
               _Symbol, g_winterOffset, (g_offsetOk || tester || !InpAutoServerOffset) ? "" : " (not connected yet, will re-detect)",
               TimeToString(ny, TIME_DATE | TIME_MINUTES), MoneyPerPointPerLot(), InpMagic);
   if(MoneyPerPointPerLot() <= 0) Print("[IMOM] WARNING: tick value unavailable, cannot size trades");
   if(!tester && !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)) Print("[IMOM] WARNING: Algo Trading is OFF in the terminal");
   // next no-trade days, so the calendar can be checked in the log
   string cal = "";
   int k0 = DayKey(ny);
   for(int i = 0; i < 45; i++)
     {
      int k = DayKey(KeyToTime(k0) + i * 86400);
      int t = DayType(k);
      int w = DowOf(KeyToTime(k));
      if(w == 0 || w == 6 || t == 1) continue;
      cal += StringFormat(" %d=%s", k, t == 0 ? "holiday" : "early-close");
     }
   PrintFormat("[IMOM] no-trade days in the next 45 days:%s", cal == "" ? " none" : cal);
   EventSetTimer(1);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason) { EventKillTimer(); }
void OnTimer() { Heartbeat(); }
void OnTick()  { g_inTick = true; Heartbeat(); g_inTick = false; }
//+------------------------------------------------------------------+
