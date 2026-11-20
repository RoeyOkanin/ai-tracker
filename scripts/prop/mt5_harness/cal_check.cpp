// Prints the EA calendar (DayType, holiday, early close, full closure) for 2016-2035 from the real EA code.
#include "mql_shim.h"
Sim* S = nullptr;
string _Symbol = "US100.cash";
bool g_timerOn = false;
#include "ea_v202.h"
int main()
  {
   S = new Sim();
   EA_v202* e = new EA_v202();
   MqlDateTime a{}; a.year = 2016; a.mon = 1; a.day = 1;
   datetime t = StructToTime(a);
   MqlDateTime b{}; b.year = 2036; b.mon = 1; b.day = 1;
   datetime end = StructToTime(b);
   for(; t < end; t += 86400)
     {
      MqlDateTime s; TimeToStruct(t, s);
      int key = s.year * 10000 + s.mon * 100 + s.day;
      printf("%d,%d,%d,%d,%d\n", key, e->DayType(key), (int)e->IsNyseHoliday(key), (int)e->IsEarlyClose(key), (int)e->IsFullClosure(key));
     }
   return 0;
  }
