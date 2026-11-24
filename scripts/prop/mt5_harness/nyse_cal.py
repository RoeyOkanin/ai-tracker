"""NYSE calendar rules exactly as they will be coded in the EA (MQL5 port must mirror this)."""
import datetime as dt

def dow(y, m, d):            # 0=Sun .. 6=Sat (MQL5 day_of_week)
    return (dt.date(y, m, d).weekday() + 1) % 7

def nth_weekday(y, m, wd, n):
    first = 1 + (wd - dow(y, m, 1) + 7) % 7
    return first + 7 * (n - 1)

def last_weekday(y, m, wd):
    last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
    return last - (dow(y, m, last) - wd + 7) % 7

def easter(y):               # anonymous Gregorian algorithm
    a = y % 19; b = y // 100; c = y % 100; d = b // 4; e = b % 4; f = (b + 8) // 25; g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30; i = c // 4; k = c % 4; l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451; mo = (h + l - 7 * m + 114) // 31; da = ((h + l - 7 * m + 114) % 31) + 1
    return mo, da

def key(y, m, d): return y * 10000 + m * 100 + d

def observed(y, m, d):       # Sat -> Fri, Sun -> Mon
    w = dow(y, m, d); t = dt.date(y, m, d)
    if w == 6: t -= dt.timedelta(days=1)
    elif w == 0: t += dt.timedelta(days=1)
    return key(t.year, t.month, t.day)

def holidays(y):
    h = set()
    if dow(y, 1, 1) == 0: h.add(key(y, 1, 2))
    elif dow(y, 1, 1) != 6: h.add(key(y, 1, 1))           # Saturday New Year: no holiday
    h.add(key(y, 1, nth_weekday(y, 1, 1, 3)))              # MLK
    h.add(key(y, 2, nth_weekday(y, 2, 1, 3)))              # Presidents
    em, ed = easter(y); gf = dt.date(y, em, ed) - dt.timedelta(days=2); h.add(key(gf.year, gf.month, gf.day))
    h.add(key(y, 5, last_weekday(y, 5, 1)))                # Memorial
    if y >= 2022: h.add(observed(y, 6, 19))                # Juneteenth
    h.add(observed(y, 7, 4))
    h.add(key(y, 9, nth_weekday(y, 9, 1, 1)))              # Labor
    h.add(key(y, 11, nth_weekday(y, 11, 4, 4)))            # Thanksgiving
    h.add(observed(y, 12, 25))
    return h

def early_closes(y):
    e = set()
    e.add(key(y, 11, nth_weekday(y, 11, 4, 4) + 1))        # day after Thanksgiving
    if 1 <= dow(y, 12, 24) <= 4: e.add(key(y, 12, 24))
    if 1 <= dow(y, 7, 3) <= 4: e.add(key(y, 7, 3))
    return e

def full_closure(k):         # market (CME too) closed the whole day: weekend, New Year, Good Friday, Christmas
    y, m, d = k // 10000, (k // 100) % 100, k % 100
    w = dow(y, m, d)
    if w in (0, 6): return True
    em, ed = easter(y); gf = dt.date(y, em, ed) - dt.timedelta(days=2)
    if k == key(gf.year, gf.month, gf.day): return True
    if k in (observed(y, 12, 25),): return True
    if dow(y, 1, 1) == 0 and k == key(y, 1, 2): return True
    if k == key(y, 1, 1): return True
    return False

def day_type(k):             # 0 closed, 1 regular, 2 early close
    y, m, d = k // 10000, (k // 100) % 100, k % 100
    if dow(y, m, d) in (0, 6) or k in holidays(y): return 0
    if k in early_closes(y): return 2
    return 1
