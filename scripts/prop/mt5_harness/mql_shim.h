// Minimal MQL5 runtime so the EA source (.mq5, after prep_mq5.py) compiles and runs under g++.
// Market + broker are simulated in Sim (US100.cash-like CFD, hedging account, FTMO-style server time).
#pragma once
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdarg>
#include <cmath>
#include <ctime>
#include <string>
#include <vector>
#include <map>
#include <array>
#include <deque>
#include <algorithm>

typedef long long datetime;
// ulong comes from <sys/types.h> (unsigned long, 64-bit on Linux like MQL5)
typedef unsigned int uint;
typedef unsigned short ushort;
typedef unsigned char uchar;
using string = std::string;

// ---------------------------------------------------------------- enums (typed like MQL5 so misuse fails to compile)
enum ENUM_TIMEFRAMES { PERIOD_CURRENT = 0, PERIOD_M5 = 5 };
enum ENUM_POSITION_PROPERTY_INTEGER { POSITION_TICKET, POSITION_TIME, POSITION_TYPE, POSITION_MAGIC, POSITION_IDENTIFIER };
enum ENUM_POSITION_PROPERTY_DOUBLE { POSITION_VOLUME, POSITION_PRICE_OPEN, POSITION_SL, POSITION_TP, POSITION_PROFIT };
enum ENUM_POSITION_PROPERTY_STRING { POSITION_SYMBOL, POSITION_COMMENT };
enum ENUM_POSITION_TYPE { POSITION_TYPE_BUY = 0, POSITION_TYPE_SELL = 1 };
enum ENUM_DEAL_PROPERTY_INTEGER { DEAL_TICKET, DEAL_TIME, DEAL_TYPE, DEAL_ENTRY, DEAL_MAGIC, DEAL_POSITION_ID };
enum ENUM_DEAL_PROPERTY_DOUBLE { DEAL_VOLUME, DEAL_PRICE, DEAL_PROFIT, DEAL_COMMISSION, DEAL_SWAP };
enum ENUM_DEAL_PROPERTY_STRING { DEAL_SYMBOL, DEAL_COMMENT };
enum ENUM_DEAL_ENTRY { DEAL_ENTRY_IN = 0, DEAL_ENTRY_OUT = 1 };
enum ENUM_DEAL_TYPE { DEAL_TYPE_BUY = 0, DEAL_TYPE_SELL = 1, DEAL_TYPE_BALANCE = 2 };
enum ENUM_ACCOUNT_INFO_DOUBLE { ACCOUNT_BALANCE, ACCOUNT_EQUITY, ACCOUNT_MARGIN_FREE, ACCOUNT_PROFIT };
enum ENUM_ACCOUNT_INFO_INTEGER { ACCOUNT_LOGIN, ACCOUNT_LEVERAGE };
enum ENUM_SYMBOL_INFO_DOUBLE { SYMBOL_BID, SYMBOL_ASK, SYMBOL_TRADE_TICK_VALUE, SYMBOL_TRADE_TICK_SIZE,
                               SYMBOL_VOLUME_STEP, SYMBOL_VOLUME_MIN, SYMBOL_VOLUME_MAX };
enum ENUM_SYMBOL_INFO_INTEGER { SYMBOL_DIGITS };
enum ENUM_ORDER_TYPE { ORDER_TYPE_BUY = 0, ORDER_TYPE_SELL = 1 };
enum ENUM_TERMINAL_INFO_INTEGER { TERMINAL_CONNECTED, TERMINAL_TRADE_ALLOWED };
enum ENUM_MQL_INFO_INTEGER { MQL_TESTER, MQL_OPTIMIZATION };
#define TIME_DATE 1
#define TIME_MINUTES 2
#define TIME_SECONDS 4
#define FILE_READ 1
#define FILE_WRITE 2
#define FILE_CSV 8
#define FILE_ANSI 32
#define FILE_SHARE_READ 128
#define INVALID_HANDLE (-1)
#define INIT_SUCCEEDED 0
#define INIT_FAILED 1

struct MqlDateTime { int year, mon, day, hour, min, sec, day_of_week, day_of_year; };
struct MqlRates { datetime time; double open, high, low, close; long long tick_volume; int spread; long long real_volume; };

// ---------------------------------------------------------------- arrays with MQL5 "array out of range" semantics (abort)
[[noreturn]] inline void mql_fatal(const char* what, long i, long n)
  {
   fprintf(stderr, "MQL5 RUNTIME ERROR: %s index %ld size %ld\n", what, i, n);
   fflush(stdout);
   abort();
  }
template<class T> struct MqlArray
  {
   std::vector<T> v;
   T& operator[](long i) { if(i < 0 || i >= (long)v.size()) mql_fatal("array out of range", i, (long)v.size()); return v[i]; }
   const T& operator[](long i) const { if(i < 0 || i >= (long)v.size()) mql_fatal("array out of range", i, (long)v.size()); return v[i]; }
  };
template<class T, int N> struct MqlRow
  {
   T* p;
   T& operator[](long k) { if(k < 0 || k >= N) mql_fatal("array out of range (dim 2)", k, N); return p[k]; }
  };
template<class T, int N> struct MqlArray2
  {
   std::vector<std::array<T, N>> v;
   MqlRow<T, N> operator[](long i) { if(i < 0 || i >= (long)v.size()) mql_fatal("array out of range (dim 1)", i, (long)v.size()); return MqlRow<T, N>{v[i].data()}; }
  };
template<class T, int N> struct MqlFixed
  {
   T a[N] = {};
   T& operator[](long i) { if(i < 0 || i >= N) mql_fatal("fixed array out of range", i, N); return a[i]; }
  };
template<class T> int ArrayResize(MqlArray<T>& a, int n, int reserve = 0) { a.v.resize(n < 0 ? 0 : n); return (int)a.v.size(); }
template<class T, int N> int ArrayResize(MqlArray2<T, N>& a, int n, int reserve = 0) { a.v.resize(n < 0 ? 0 : n); return (int)a.v.size(); }
template<class T> int ArraySize(const MqlArray<T>& a) { return (int)a.v.size(); }
template<class T> bool ArraySetAsSeries(MqlArray<T>&, bool) { return true; }
template<class T> void ZeroMemory(T& x) { memset((void*)&x, 0, sizeof(T)); }

// ---------------------------------------------------------------- time
inline datetime StructToTime(const MqlDateTime& s)
  {
   struct tm t; memset(&t, 0, sizeof(t));
   t.tm_year = s.year - 1900; t.tm_mon = s.mon - 1; t.tm_mday = s.day; t.tm_hour = s.hour; t.tm_min = s.min; t.tm_sec = s.sec;
   return (datetime)timegm(&t);
  }
inline bool TimeToStruct(datetime x, MqlDateTime& s)
  {
   time_t tt = (time_t)x; struct tm t; gmtime_r(&tt, &t);
   s.year = t.tm_year + 1900; s.mon = t.tm_mon + 1; s.day = t.tm_mday; s.hour = t.tm_hour; s.min = t.tm_min; s.sec = t.tm_sec;
   s.day_of_week = t.tm_wday; s.day_of_year = t.tm_yday;
   return true;
  }
inline string TimeToString(datetime x, int flags = TIME_DATE | TIME_MINUTES)
  {
   MqlDateTime s; TimeToStruct(x, s);
   char b[64]; b[0] = 0; string r;
   if(flags & TIME_DATE) { snprintf(b, sizeof(b), "%04d.%02d.%02d", s.year, s.mon, s.day); r += b; }
   if(flags & (TIME_MINUTES | TIME_SECONDS))
     {
      if(!r.empty()) r += " ";
      if(flags & TIME_SECONDS) snprintf(b, sizeof(b), "%02d:%02d:%02d", s.hour, s.min, s.sec);
      else snprintf(b, sizeof(b), "%02d:%02d", s.hour, s.min);
      r += b;
     }
   return r;
  }

// ---------------------------------------------------------------- math / strings
template<class A, class B> inline auto MathMax(A a, B b) -> decltype(a + b) { return a > b ? a : b; }
template<class A, class B> inline auto MathMin(A a, B b) -> decltype(a + b) { return a < b ? a : b; }
inline double MathFloor(double x) { return std::floor(x); }
inline double MathCeil(double x) { return std::ceil(x); }
inline double MathAbs(double x) { return std::fabs(x); }
inline double MathSqrt(double x) { return std::sqrt(x); }
inline double MathRound(double x) { return std::round(x); }
inline double NormalizeDouble(double v, int d) { double m = std::pow(10.0, d); return std::round(v * m) / m; }
inline int StringLen(const string& s) { return (int)s.size(); }
inline long long StringToInteger(const string& s) { return atoll(s.c_str()); }
inline double StringToDouble(const string& s) { return atof(s.c_str()); }
inline int StringFind(const string& s, const string& m, int start = 0) { size_t p = s.find(m, start); return p == string::npos ? -1 : (int)p; }
inline string IntegerToString(long long v, int = 0, ushort = ' ') { return std::to_string(v); }
inline string DoubleToString(double v, int d = 8) { char b[64]; snprintf(b, sizeof(b), "%.*f", d, v); return b; }
inline int StringTrimLeft(string& s) { size_t p = s.find_first_not_of(" \t\r\n"); int n = (int)(p == string::npos ? s.size() : p); s.erase(0, n); return n; }
inline int StringTrimRight(string& s) { size_t p = s.find_last_not_of(" \t\r\n"); size_t keep = (p == string::npos) ? 0 : p + 1; int n = (int)(s.size() - keep); s.erase(keep); return n; }
inline int StringSplit(const string& s, ushort sep, MqlArray<string>& out)
  {
   out.v.clear();
   if(s.empty()) return 0;
   size_t a = 0;
   while(true)
     {
      size_t b = s.find((char)sep, a);
      if(b == string::npos) { out.v.push_back(s.substr(a)); break; }
      out.v.push_back(s.substr(a, b - a)); a = b + 1;
     }
   return (int)out.v.size();
  }
// printf-style helpers: prep_mq5.py wraps every argument in CV() so g++ -Wformat checks the real types
template<class T> inline T CV(T x) { return x; }
inline const char* CV(const string& s) { return s.c_str(); }
void mql_log(const char* line);
__attribute__((format(printf, 1, 2))) inline void PrintFormatC(const char* fmt, ...)
  {
   char b[2048]; va_list ap; va_start(ap, fmt); vsnprintf(b, sizeof(b), fmt, ap); va_end(ap); mql_log(b);
  }
__attribute__((format(printf, 1, 2))) inline string StringFormatC(const char* fmt, ...)
  {
   char b[2048]; va_list ap; va_start(ap, fmt); vsnprintf(b, sizeof(b), fmt, ap); va_end(ap); return b;
  }
inline void Print(const string& s) { mql_log(s.c_str()); }

// ---------------------------------------------------------------- simulated market + broker
struct SimBar { datetime t; double o, h, l, c; long long v; };
struct SimPos { ulong ticket; int type; double vol, price, sl; long long magic; string sym, comment; datetime t; };
struct SimDeal { ulong ticket; datetime t; int type, entry; long long magic; string sym, comment; double vol, price, profit, sl; ulong pos; };
struct SimFault { datetime a, b; int rc; bool closes, opens, partial = false, ghost = false; int late = 0; };
// ghost: the order is executed on the server but OrderSend reports failure rc (reply lost). late: an open is reported as failed (rc) and executed `late` seconds afterwards.
struct SimLate { datetime t; int type; double vol, sl; long long magic; string sym, cm; };
struct SimHide { datetime a, b, h0, h1; };   // while a <= now < b, bars with h0 <= t < h1 are not in the terminal's history yet

struct Sim
  {
   std::vector<SimBar> bars;
   long cur = -1;                 // bar holding the last tick (bar 0)
   SimBar part{};                 // partial bar 0
   datetime now = 0, lastTick = 0;
   double mid = 0, spread = 0, spreadBp = 0, slipBp = 0;
   bool open = false;
   double balance = 100000, leverage = 30, volMax = 100, slip = 0;
   std::vector<SimPos> pos;
   std::vector<SimDeal> deals;
   std::vector<int> sel;
   int psel = -1;
   ulong nextTicket = 1000;
   std::map<string, double> gv;
   bool connected = true, algo = true, tester = false;
   datetime syncUntil = 0;                          // terminal just started: not logged in yet, account/positions not loaded
   datetime eqZeroUntil = 0;                        // only ACCOUNT_EQUITY reads 0 (user reports of a running EA seeing equity 0)
   long long login = 1515290765;
   std::vector<SimFault> faults;
   std::vector<SimHide> hides;                      // sorted by a, non-overlapping
   std::map<int, int> reqAllByDay, reqSrvByDay;    // NY day -> requests (all / reaching the server)
   long long reqAll = 0, reqSrv = 0, slHits = 0;
   FILE* logf = stdout;
   bool quiet = false;
   long long logLines = 0;
   std::map<string, long long> tagCount;            // counts of "[IMOM] <first word>" lines
   std::map<int, datetime> guardAt;                 // NY day -> first time the EA logged EQUITY GUARD (invariant check)
   datetime targetDoneAt = 0;                       // first "PROFIT TARGET DONE" (invariant check)

   // view=1: the EA sees the terminal's copy of the trade state, taken at the start of each event. Its own
   // OrderSend results (positions, balance, deals) show up from the next event on (MT5 updates the trade
   // environment asynchronously), and while disconnected nothing new arrives (no ticks, prices/bars/account frozen).
   int viewMode = 0;
   struct View { std::vector<SimPos> pos; double balance = 0, equity = 0, freeMargin = 0, profit = 0, bid = 0, ask = 0; long cur = -1; SimBar part{}; datetime lastTick = 0; size_t ndeals = 0; } v;
   // tradelag=N (round 5): positions / deals reach the terminal N seconds after the server changed them (prices stay live);
   // ballag=M: the account balance arrives another M seconds later (positions and balance are not updated together).
   int tradeLag = 0, balLag = 0;
   struct TSnap { datetime t; std::vector<SimPos> pos; size_t ndeals; double balance; };
   std::deque<TSnap> lagQ; std::deque<std::pair<datetime, double>> balQ;
   std::vector<SimPos> visPos; size_t visDeals = 0; double visBal = 0; bool visInit = false;
   std::vector<SimLate> lateQ;
   long long staleCloseReq = 0;                     // closes sent for a position that was already gone on the server (10036)
   void tradeChanged()
     {
      if(tradeLag > 0 || balLag > 0) { lagQ.push_back({now + tradeLag, pos, deals.size(), balance}); balQ.push_back({now + tradeLag + balLag, balance}); }
     }
   void resetLag() { lagQ.clear(); balQ.clear(); visInit = false; }   // terminal restart: full sync from the server
   void snap()
     {
      if(tradeLag > 0 || balLag > 0)
        {
         if(!visInit) { visPos = pos; visDeals = deals.size(); visBal = balance; visInit = true; }
         while(!lagQ.empty() && lagQ.front().t <= now) { visPos = lagQ.front().pos; visDeals = lagQ.front().ndeals; lagQ.pop_front(); }
         while(!balQ.empty() && balQ.front().first <= now) { visBal = balQ.front().second; balQ.pop_front(); }
         v.pos = visPos; v.ndeals = visDeals; v.balance = visBal;
         double f = 0, m = 0;
         for(auto& p : v.pos) { f += (p.type == 0 ? (bid() - p.price) : (p.price - ask())) * p.vol; m += p.vol * p.price / leverage; }
         v.profit = f; v.equity = v.balance + f; v.freeMargin = v.equity - m;
        }
      else { v.pos = pos; v.balance = balance; v.equity = equity(); v.freeMargin = equity() - marginUsed(); v.profit = floating(); v.ndeals = deals.size(); }
      v.bid = bid(); v.ask = ask(); v.cur = cur; v.part = part; v.lastTick = lastTick;
     }
   const std::vector<SimPos>& vpos() const { return viewMode ? v.pos : pos; }
   bool unsynced() const { return now < syncUntil; }
   double spr() const { return spread + mid * spreadBp / 10000.0; }
   double bid() const { return mid - spr() / 2; }
   double ask() const { return mid + spr() / 2; }
   double slp() const { return slip + mid * slipBp / 10000.0; }
   static bool usDst(datetime utc)
     {
      MqlDateTime s; TimeToStruct(utc, s);
      auto nth = [](int y, int mo, int n) { MqlDateTime a{}; a.year = y; a.mon = mo; a.day = 1; datetime t = StructToTime(a); MqlDateTime b; TimeToStruct(t, b); return 1 + (7 - b.day_of_week) % 7 + 7 * (n - 1); };
      MqlDateTime a{}; a.year = s.year; a.mon = 3; a.day = nth(s.year, 3, 2); a.hour = 7; datetime st = StructToTime(a);
      MqlDateTime e{}; e.year = s.year; e.mon = 11; e.day = nth(s.year, 11, 1); e.hour = 6; datetime en = StructToTime(e);
      return utc >= st && utc < en;
     }
   datetime gmt() const { datetime u = now - 2 * 3600; if(usDst(u)) u = now - 3 * 3600; return u; }
   static int nyKey(datetime srv) { MqlDateTime s; TimeToStruct(srv - 7 * 3600, s); return s.year * 10000 + s.mon * 100 + s.day; }
   double floating() const
     {
      double f = 0;
      for(auto& p : pos) f += (p.type == 0 ? (bid() - p.price) : (p.price - ask())) * p.vol;   // $1 per point per lot
      return f;
     }
   double equity() const { return balance + floating(); }
   double marginUsed() const { double m = 0; for(auto& p : pos) m += p.vol * p.price / leverage; return m; }
   // request gate: returns retcode
   uint gate(bool isClose)
     {
      reqAll++; reqAllByDay[nyKey(now)]++;
      if(!algo) return 10027;
      if(!connected || unsynced()) return 10031;
      reqSrv++; reqSrvByDay[nyKey(now)]++;
      for(auto& f : faults) if(now >= f.a && now < f.b && (isClose ? f.closes : f.opens)) return (uint)f.rc;
      if(!open) return 10018;
      return 10009;
     }
   void addDeal(int type, int entry, long long magic, const string& sym, double vol, double price, double profit, ulong posTk, const string& cm)
     {
      SimDeal d; d.ticket = nextTicket++; d.t = now; d.type = type; d.entry = entry; d.magic = magic; d.sym = sym;
      d.vol = vol; d.price = price; d.profit = profit; d.pos = posTk; d.comment = cm; d.sl = 0;
      deals.push_back(d);
     }
   void closeAt(size_t i, double px, const string& why)
     {
      SimPos p = pos[i];
      double pr = (p.type == 0 ? (px - p.price) : (p.price - px)) * p.vol;
      balance += pr;
      addDeal(p.type == 0 ? 1 : 0, 1, p.magic, p.sym, p.vol, px, pr, p.ticket, why);
      pos.erase(pos.begin() + i);
      tradeChanged();
     }
   void runLate()                                   // orders the terminal gave up on (timeout) that the server executes afterwards
     {
      for(size_t i = 0; i < lateQ.size();)
        {
         if(lateQ[i].t > now) { i++; continue; }
         SimLate q = lateQ[i]; lateQ.erase(lateQ.begin() + i);
         double px = q.type == 0 ? ask() : bid();
         if(!open || (q.sl > 0 && ((q.type == 0 && q.sl >= bid()) || (q.type == 1 && q.sl <= ask())))) continue;
         SimPos p; p.ticket = nextTicket++; p.type = q.type; p.vol = q.vol; p.price = px; p.sl = q.sl; p.magic = q.magic; p.sym = q.sym; p.comment = q.cm; p.t = now;
         pos.push_back(p);
         addDeal(q.type, 0, q.magic, q.sym, q.vol, px, 0, p.ticket, q.cm);
         deals.back().sl = q.sl;
         tradeChanged();
        }
     }
   void checkStops()
     {
      for(size_t i = 0; i < pos.size();)
        {
         auto& p = pos[i];
         if(p.sl > 0 && ((p.type == 0 && bid() <= p.sl) || (p.type == 1 && ask() >= p.sl)))
           { slHits++; closeAt(i, p.type == 0 ? bid() : ask(), "sl"); continue; }
         i++;
        }
     }
  };
extern Sim* S;
extern string _Symbol;

inline void mql_log(const char* line)
  {
   S->logLines++;
   const char* p = strstr(line, "[IMOM] ");
   if(strstr(line, "EQUITY GUARD:") && !S->guardAt.count(Sim::nyKey(S->now))) S->guardAt[Sim::nyKey(S->now)] = S->now;
   if(strstr(line, "PROFIT TARGET DONE") && !S->targetDoneAt) S->targetDoneAt = S->now;
   if(p) { p += 7; const char* e = p; while(*e && *e != ' ' && *e != ':' && *e != '(') e++; S->tagCount[string(p, e - p)]++; }
   if(S->quiet) return;
   fprintf(S->logf, "%s NY %s | %s\n", TimeToString(S->now, TIME_DATE | TIME_SECONDS).c_str(),
           TimeToString(S->now - 7 * 3600, TIME_MINUTES | TIME_SECONDS).c_str(), line);
  }

// ---------------------------------------------------------------- terminal / account / symbol
inline datetime TimeTradeServer() { return S->now; }
inline datetime TimeCurrent() { return S->viewMode ? S->v.lastTick : S->lastTick; }
inline datetime TimeGMT() { return S->gmt(); }
inline datetime TimeLocal() { return S->gmt(); }   // VPS in London (winter)
inline long long TerminalInfoInteger(ENUM_TERMINAL_INFO_INTEGER p) { return p == TERMINAL_CONNECTED ? (S->connected && !S->unsynced()) : S->algo; }
inline int MQLInfoInteger(ENUM_MQL_INFO_INTEGER p) { return p == MQL_TESTER ? S->tester : 0; }
inline double AccountInfoDouble(ENUM_ACCOUNT_INFO_DOUBLE p)
  {
   if(S->unsynced()) return 0;                      // before the login completes (MQL5 forum: account info valid only after the first tick)
   if(p == ACCOUNT_EQUITY && S->now < S->eqZeroUntil) return 0;
   if(S->viewMode)
      switch(p)
        {
         case ACCOUNT_BALANCE: return S->v.balance;
         case ACCOUNT_EQUITY: return S->v.equity;
         case ACCOUNT_MARGIN_FREE: return S->v.freeMargin;
         case ACCOUNT_PROFIT: return S->v.profit;
        }
   switch(p)
     {
      case ACCOUNT_BALANCE: return S->balance;
      case ACCOUNT_EQUITY: return S->equity();
      case ACCOUNT_MARGIN_FREE: return S->equity() - S->marginUsed();
      case ACCOUNT_PROFIT: return S->floating();
     }
   return 0;
  }
inline long long AccountInfoInteger(ENUM_ACCOUNT_INFO_INTEGER p) { if(S->unsynced()) return 0; return p == ACCOUNT_LOGIN ? S->login : (long long)S->leverage; }
inline double SymbolInfoDouble(const string&, ENUM_SYMBOL_INFO_DOUBLE p)
  {
   switch(p)
     {
      case SYMBOL_BID: return S->viewMode ? S->v.bid : S->bid();
      case SYMBOL_ASK: return S->viewMode ? S->v.ask : S->ask();
      case SYMBOL_TRADE_TICK_VALUE: return 0.01;
      case SYMBOL_TRADE_TICK_SIZE: return 0.01;
      case SYMBOL_VOLUME_STEP: return 0.01;
      case SYMBOL_VOLUME_MIN: return 0.01;
      case SYMBOL_VOLUME_MAX: return S->volMax;
     }
   return 0;
  }
inline long long SymbolInfoInteger(const string&, ENUM_SYMBOL_INFO_INTEGER) { return 2; }
inline bool OrderCalcMargin(ENUM_ORDER_TYPE, const string&, double vol, double px, double& margin) { margin = vol * px / S->leverage; return true; }
// (CTrade below always acts on the live server state: prices, positions and margin at the moment of the request)

// ---------------------------------------------------------------- bars
inline long sim_bar_index_at_or_before(datetime t)
  {
   // last bar index with time <= t, limited to bars that exist already (<= cur)
   long lo = 0, hi = S->viewMode ? S->v.cur : S->cur, ans = -1;
   while(lo <= hi) { long m = (lo + hi) / 2; if(S->bars[m].t <= t) { ans = m; lo = m + 1; } else hi = m - 1; }
   return ans;
  }
inline datetime iTime(const string&, ENUM_TIMEFRAMES, int shift)
  {
   long cur = S->viewMode ? S->v.cur : S->cur;
   long i = cur - shift;
   if(cur < 0 || i < 0) return 0;
   return S->bars[i].t;
  }
inline const SimHide* sim_active_hide()
  {
   auto& h = S->hides;
   if(h.empty()) return nullptr;
   auto it = std::upper_bound(h.begin(), h.end(), S->now, [](datetime t, const SimHide& x) { return t < x.a; });
   if(it == h.begin()) return nullptr;
   --it;
   return (S->now >= it->a && S->now < it->b) ? &*it : nullptr;
  }
inline int CopyRates(const string&, ENUM_TIMEFRAMES, datetime start, datetime stop, MqlArray<MqlRates>& out)
  {
   out.v.clear();
   const SimHide* hide = sim_active_hide();
   long cur = S->viewMode ? S->v.cur : S->cur;
   const SimBar& part = S->viewMode ? S->v.part : S->part;
   if(cur < 0) return -1;
   long b = sim_bar_index_at_or_before(stop);
   if(b < 0) return 0;
   long a = b;
   while(a > 0 && S->bars[a - 1].t >= start) a--;
   if(S->bars[a].t < start) return 0;
   for(long i = a; i <= b; i++)
     {
      if(hide && S->bars[i].t >= hide->h0 && S->bars[i].t < hide->h1) continue;
      const SimBar& x = (i == cur) ? part : S->bars[i];
      MqlRates r; r.time = S->bars[i].t; r.open = x.o; r.high = x.h; r.low = x.l; r.close = x.c; r.tick_volume = x.v; r.spread = 0; r.real_volume = 0;
      out.v.push_back(r);
     }
   return (int)out.v.size();
  }

// ---------------------------------------------------------------- positions / history
inline int PositionsTotal() { return S->unsynced() ? 0 : (int)S->vpos().size(); }
inline ulong PositionGetTicket(int i) { if(i < 0 || i >= (int)S->vpos().size()) { S->psel = -1; return 0; } S->psel = i; return S->vpos()[i].ticket; }
inline long long PositionGetInteger(ENUM_POSITION_PROPERTY_INTEGER p)
  {
   if(S->psel < 0 || S->psel >= (int)S->vpos().size()) return 0;
   auto& x = S->vpos()[S->psel];
   switch(p) { case POSITION_TICKET: case POSITION_IDENTIFIER: return (long long)x.ticket; case POSITION_TIME: return x.t; case POSITION_TYPE: return x.type; case POSITION_MAGIC: return x.magic; }
   return 0;
  }
inline double PositionGetDouble(ENUM_POSITION_PROPERTY_DOUBLE p)
  {
   if(S->psel < 0 || S->psel >= (int)S->vpos().size()) return 0;
   auto& x = S->vpos()[S->psel];
   double bid = S->viewMode ? S->v.bid : S->bid(), ask = S->viewMode ? S->v.ask : S->ask();
   switch(p) { case POSITION_VOLUME: return x.vol; case POSITION_PRICE_OPEN: return x.price; case POSITION_SL: return x.sl; case POSITION_TP: return 0;
      case POSITION_PROFIT: return (x.type == 0 ? (bid - x.price) : (x.price - ask)) * x.vol; }
   return 0;
  }
inline string PositionGetString(ENUM_POSITION_PROPERTY_STRING p) { if(S->psel < 0 || S->psel >= (int)S->vpos().size()) return ""; return p == POSITION_SYMBOL ? S->vpos()[S->psel].sym : S->vpos()[S->psel].comment; }
inline bool HistorySelect(datetime from, datetime to)
  {
   S->sel.clear();
   int nd = S->viewMode ? (int)S->v.ndeals : (int)S->deals.size();
   for(int i = 0; i < nd; i++) if(S->deals[i].t >= from && S->deals[i].t <= to) S->sel.push_back(i);
   return true;
  }
inline int HistoryDealsTotal() { return (int)S->sel.size(); }
inline ulong HistoryDealGetTicket(int i) { if(i < 0 || i >= (int)S->sel.size()) return 0; return S->deals[S->sel[i]].ticket; }
inline const SimDeal* sim_deal(ulong tk) { for(int i : S->sel) if(S->deals[i].ticket == tk) return &S->deals[i]; return nullptr; }
inline long long HistoryDealGetInteger(ulong tk, ENUM_DEAL_PROPERTY_INTEGER p)
  {
   const SimDeal* d = sim_deal(tk); if(!d) return 0;
   switch(p) { case DEAL_TICKET: return (long long)d->ticket; case DEAL_TIME: return d->t; case DEAL_TYPE: return d->type; case DEAL_ENTRY: return d->entry; case DEAL_MAGIC: return d->magic; case DEAL_POSITION_ID: return (long long)d->pos; }
   return 0;
  }
inline double HistoryDealGetDouble(ulong tk, ENUM_DEAL_PROPERTY_DOUBLE p)
  {
   const SimDeal* d = sim_deal(tk); if(!d) return 0;
   switch(p) { case DEAL_VOLUME: return d->vol; case DEAL_PRICE: return d->price; case DEAL_PROFIT: return d->profit; case DEAL_COMMISSION: return 0; case DEAL_SWAP: return 0; }
   return 0;
  }
inline string HistoryDealGetString(ulong tk, ENUM_DEAL_PROPERTY_STRING p) { const SimDeal* d = sim_deal(tk); if(!d) return ""; return p == DEAL_SYMBOL ? d->sym : d->comment; }

// ---------------------------------------------------------------- global variables / files / events
inline datetime GlobalVariableSet(const string& n, double v) { S->gv[n] = v; return S->now; }
inline double GlobalVariableGet(const string& n) { auto it = S->gv.find(n); return it == S->gv.end() ? 0 : it->second; }
inline bool GlobalVariableCheck(const string& n) { return S->gv.count(n) > 0; }
inline void GlobalVariablesFlush() {}
inline int FileOpen(const string&, int, ushort = ';') { return INVALID_HANDLE; }
inline bool FileSeek(int, long long, int) { return true; }
template<class... A> inline uint FileWrite(int, A...) { return 0; }
inline void FileClose(int) {}
extern bool g_timerOn;
inline bool EventSetTimer(int) { g_timerOn = true; return true; }
inline void EventKillTimer() { g_timerOn = false; }

// ---------------------------------------------------------------- CTrade (hedging account, market execution)
class CTrade
  {
   long long m_magic = 0;
   uint m_rc = 0;
   bool open_(int type, double vol, const string& sym, double sl, const string& cm)
     {
      m_rc = S->gate(false);
      if(m_rc != 10009) return false;
      if(vol <= 0 || vol > S->volMax + 1e-9) { m_rc = 10014; return false; }
      double px = type == 0 ? S->ask() : S->bid();
      if(sl > 0 && ((type == 0 && sl >= S->bid()) || (type == 1 && sl <= S->ask()))) { m_rc = 10016; return false; }
      if(vol * px / S->leverage > S->equity() - S->marginUsed()) { m_rc = 10019; return false; }
      const SimFault* gf = nullptr;
      for(auto& f : S->faults) if(S->now >= f.a && S->now < f.b && (f.ghost || f.late > 0)) gf = &f;
      if(gf && gf->late > 0) { S->lateQ.push_back(SimLate{S->now + gf->late, type, vol, sl, m_magic, sym, cm}); m_rc = (uint)gf->rc; return false; }
      SimPos p; p.ticket = S->nextTicket++; p.type = type; p.vol = vol; p.price = px; p.sl = sl; p.magic = m_magic; p.sym = sym; p.comment = cm; p.t = S->now;
      S->pos.push_back(p);
      S->addDeal(type, 0, m_magic, sym, vol, px, 0, p.ticket, cm);
      S->deals.back().sl = sl;
      S->tradeChanged();
      if(gf) { m_rc = (uint)gf->rc; return false; }               // executed, but the reply never reached the terminal
      return true;
     }
public:
   void SetExpertMagicNumber(long long m) { m_magic = m; }
   bool SetTypeFillingBySymbol(const string&) { return true; }
   void SetDeviationInPoints(ulong) {}
   bool Buy(double vol, const string& sym, double = 0, double sl = 0, double = 0, const string& cm = "") { return open_(0, vol, sym, sl, cm); }
   bool Sell(double vol, const string& sym, double = 0, double sl = 0, double = 0, const string& cm = "") { return open_(1, vol, sym, sl, cm); }
   bool PositionClose(ulong ticket, ulong = ~0ULL)
     {
      m_rc = 0;
      size_t i = 0;
      for(; i < S->pos.size(); i++) if(S->pos[i].ticket == ticket) break;
      if(i == S->pos.size())
        {
         // CTrade selects the position in the terminal's (possibly stale) list first; if it is still listed there the
         // request goes to the server, which answers 10036 "position already closed"
         bool listed = false;
         if(S->viewMode) for(auto& p : S->v.pos) if(p.ticket == ticket) listed = true;
         if(!listed) return false;                                // like CTrade: retcode cleared, false
         m_rc = S->gate(true);
         if(m_rc == 10009) { m_rc = 10036; S->staleCloseReq++; }
         return false;
        }
      m_rc = S->gate(true);
      if(m_rc != 10009) return false;
      for(auto& f : S->faults)
         if(f.partial && S->now >= f.a && S->now < f.b && S->pos[i].vol >= 0.02)
           {
            SimPos& p = S->pos[i];
            double half = std::floor(p.vol / 2 * 100 + 1e-9) / 100, px = p.type == 0 ? S->bid() - S->slp() : S->ask() + S->slp();
            double pr = (p.type == 0 ? (px - p.price) : (p.price - px)) * half;
            S->balance += pr; p.vol = std::round((p.vol - half) * 100) / 100;
            S->addDeal(p.type == 0 ? 1 : 0, 1, p.magic, p.sym, half, px, pr, p.ticket, "ea close (partial)");
            S->tradeChanged();
            m_rc = 10010;
            return true;                                                // OrderSend true, DONE_PARTIAL
           }
      S->closeAt(i, S->pos[i].type == 0 ? S->bid() - S->slp() : S->ask() + S->slp(), "ea close");
      for(auto& f : S->faults) if(f.ghost && S->now >= f.a && S->now < f.b) { m_rc = (uint)f.rc; return false; }   // closed, reply lost
      return true;
     }
   uint ResultRetcode() const { return m_rc; }
   string ResultRetcodeDescription() const
     {
      switch(m_rc) { case 10009: return "done"; case 10010: return "done partially"; case 10018: return "market closed"; case 10027: return "autotrading disabled by client";
         case 10031: return "no connection"; case 10004: return "requote"; case 10006: return "request rejected"; case 10016: return "invalid stops"; case 10019: return "no money"; case 10012: return "request canceled by timeout"; case 10036: return "position already closed"; }
      return "retcode " + std::to_string(m_rc);
     }
  };
