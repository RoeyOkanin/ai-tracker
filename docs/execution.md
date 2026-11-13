# ביצוע: מהחלטה לפקודה

המנוע מחליט אחרי כל סגירה, וכותב את `docs/data/target_book.json`: איך התיק צריך להיראות אחרי הסגירה הבאה.
המבצע (`scripts/execute.py`) משווה את זה לחשבון ושולח את ההפרש כפקודות **Market On Close**, כלומר באותו מחיר שהבקטסט מניח.

```
סגירה (יום א')                 למחרת 19:05 UTC                      סגירה (יום ב')
compute.py → target_book.json → execute.py → פקודות MOC → ברוקר → ביצוע
```

## שלושה מצבים

| מצב | למי | מה קורה |
|---|---|---|
| **כרטיס** (`--broker ticket`) | Colmex Pro, או כל ברוקר בלי API | כל ערב, ב-issue היומי, מגיעה טבלה: מניה, קנייה/מכירה, כמות. אתה שולח ב-TradingView. המערכת מניחה שבוצע ומנהלת תיק צל ב-`data/manual_book.json`. |
| **אוטומטי, נייר** (`--broker alpaca`, `mode: paper`) | הוכחה שהמערכת סוחרת לבד | GitHub Actions שולח פקודות לחשבון נייר של Alpaca כל יום מסחר. |
| **אוטומטי, אמיתי** | אחרי חודש נייר נקי | `mode: live` ב-`config/execution.yaml` **וגם** הסוד `LIVE_TRADING_CONFIRM=YES`. שני מנעולים. |

## הפעלת אוטומטי (נייר) ב-5 דקות

1. נרשמים ב-[alpaca.markets](https://alpaca.markets) → Paper Trading → Generate API Keys.
2. בריפו: Settings → Secrets and variables → Actions → New repository secret:
   - `ALPACA_KEY_ID`
   - `ALPACA_SECRET_KEY`
3. Actions → trade → Run workflow (מסומן dry run) כדי לראות את התוכנית בלי לשלוח.
4. מעכשיו זה רץ לבד כל יום מסחר.

## הגנות

- **מתג חירום:** `enabled: false` ב-`config/execution.yaml`. המבצע מדפיס תוכנית ולא שולח כלום.
- רק מניות מתוך `companies.yaml`. אחזקות אחרות בחשבון לא נוגעים בהן.
- תקרה לפקודה (35% מההון), תקרה למספר פקודות ולמחזור יומי. חריגה = המבצע מסרב לסחור.
- ספר ישן (הריצה של אתמול נכשלה), שוק סגור, או אחרי 15:45 בניו יורק = לא סוחרים.
- `client_order_id` קבוע לכל יום ומניה, כך שהרצה כפולה לא שולחת פקודה כפולה.
- כל פקודה נרשמת ב-`data/execution_log.csv`.

## TradingView

- `tradingview/ai_tracker_exits.pine`: על כל מניה שמוחזקת. מציג את הסטופ הנגרר וקו היציאה של ממוצע 200, ומתריע על הסגירה. מזינים תאריך כניסה ואחוז סטופ מהדשבורד.
- `tradingview/ai_tracker_regime.pine`: על SMH. החצי של מצב השוק שאפשר לראות על גרף.

למה המוח לא ב-Pine: האסטרטגיה מדרגת 93 מניות זו מול זו כל יום. Pine מוגבל ל-40 סימבולים לסקריפט ולא בנוי לדירוג רוחבי.
TradingView לא שולח פקודות לברוקר מחובר מתוך התראה, אז הוא משמש כאן לתצוגה ולהתראות.
