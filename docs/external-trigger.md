# מפעיל חיצוני לריצת ה-trade

ה-cron של GitHub רץ בריפו הזה באיחור של 4 עד 7 שעות (נמדד: daily-update, switch-strategy ו-trade), וחלון ה-MOC נסגר ב-15:50 שעון ניו יורק.
לכן שירות חינמי קורא ל-GitHub בשעה מדויקת, ו-GitHub מריץ מיד (`workflow_dispatch` לא מתעכב כמו `schedule`).
ה-cron הפנימי נשאר כגיבוי, ו-`client_order_id` קבוע ליום ולמניה, כך שריצה כפולה לא מכפילה פקודות.

## הקמה (10 דקות, פעם אחת)

### 1. טוקן מוגבל ב-GitHub
[GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token](https://github.com/settings/personal-access-tokens/new)
- Repository access: **Only select repositories** → `ai-tracker`
- Permissions → Repository permissions → **Actions: Read and write** (שום דבר אחר)
- Expiration: 90 יום (ושים תזכורת לחדש)
- מעתיקים את הטוקן. הוא יוצג פעם אחת.

### 2. משימה ב-[cron-job.org](https://cron-job.org) (חינם)
- Create cronjob
- **URL:** `https://api.github.com/repos/RoeyOkanin/ai-tracker/actions/workflows/trade.yml/dispatches`
- **Advanced → Request method:** `POST`
- **Request body:** `{"ref":"main","inputs":{"dry_run":"false"}}`
- **Headers:**
  - `Authorization: Bearer <הטוקן>`
  - `Accept: application/vnd.github+json`
  - `X-GitHub-Api-Version: 2022-11-28`
  - `Content-Type: application/json`
- **Schedule:** User-defined, **Time zone: America/New_York**, שעה 14, דקה 15, ימים שני עד שישי. (אזור הזמן שם מטפל במעבר שעון חורף/קיץ לבד.)
- **Notifications:** לסמן "on failure" אל המייל שלך.
- הצלחה = קוד 204.

### 3. בדיקה
ב-cron-job.org לוחצים "Test run" עם `"dry_run":"true"` בגוף. אמורה להופיע ריצת trade חדשה בלשונית Actions תוך שניות, והיא לא שולחת פקודות.
לפני המעבר לאמיתי מחזירים ל-`"false"`.

## מה לא מכוסה
- אם cron-job.org או GitHub נופלים בדיוק באותה דקה, מגיעה התראה (issue או מייל) ולא נשלחות פקודות.
- זה פותר את התזמון בלבד. לפני כסף אמיתי עדיין כדאי להעביר את המבצע לשרת קטן.
