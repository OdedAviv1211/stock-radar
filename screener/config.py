"""הגדרות הכלי – אפשר לשנות כאן ספים ומשקלים בלי לגעת בקוד."""

# ---------- יקום המניות ----------
US_MIN_MARKET_CAP = 300e6        # שווי שוק מינימלי בארה"ב ($) – כולל מניות קטנות
US_MIN_PRICE = 5.0               # מחיר מינימלי ($)
US_MIN_DOLLAR_VOL = 10e6         # מחזור יומי ממוצע מינימלי לכניסה לטופ ($)
TASE_MIN_DOLLAR_VOL = 1e6        # מחזור יומי ממוצע מינימלי בת"א (בדולרים)

# סיווג לפי שווי שוק (בדולרים)
CAP_CLASSES = [
    (200e9, "מגה"),
    (10e9, "גדולה"),
    (2e9, "בינונית"),
    (0, "קטנה"),
]

HISTORY_PERIOD = "2y"            # היסטוריה יומית לניתוח
DOWNLOAD_CHUNK = 200             # כמה מניות בכל בקשת הורדה
N_FUNDAMENTALS = 160             # כמה מועמדות מובילות מקבלות ניתוח פונדמנטלי

# ---------- משקלות הציון (פרופיל: צמיחה אגרסיבית) ----------
WEIGHTS = {
    "trend": 0.20,      # מגמה: ממוצע 150, שלב 2 של Weinstein, Trend Template של Minervini
    "rs": 0.20,         # חוזק יחסי (IBD RS Rating)
    "fund": 0.16,       # צמיחה בהכנסות ורווחים (CANSLIM C+A), מרווחים, ROE
    "group": 0.12,      # חוזק הענף/תעשייה (IBD Industry Group Rank)
    "analog": 0.12,     # דמיון למניות שהתפוצצו בעבר (NVDA, SMCI, PLTR...)
    "setup": 0.12,      # מבנה לפני פריצה: פיבוט, VCP, תבניות גרף
    "accum": 0.08,      # איסוף מוסדי: נפח בימי עלייה מול ימי ירידה
}
# אם קיימת כיול מהבדיקה לאחור (data/weights.json) והוא שיפר תוצאות מחוץ למדגם – הוא ישמש במקום
USE_CALIBRATED_WEIGHTS = True

TOP_N = 10
MAX_PER_THEME = 3        # פיזור: לא יותר מ-3 מניות מאותה קטגוריה בטופ 10
ISRAEL_TOP_N = 5
TABLE_N = 150            # כמה מניות להציג בטבלה המלאה
HEATMAP_PER_SECTOR = 30  # כמה מניות (לפי שווי) בכל סקטור במפת החום

BENCH_US = "SPY"
BENCH_US2 = "QQQ"
BENCH_TASE = "^TA125.TA"
FX_ILS = "ILS=X"

# ---------- דוחות רבעוניים ----------
EARNINGS_WARN_DAYS = 10      # אזהרה אם דוח בעוד פחות מ-X ימים
EARNINGS_PENALTY_DAYS = 5    # הורדת ציון אם הדוח ממש קרוב
EARNINGS_PENALTY = 4.0

# ---------- תיק אישי ----------
DEFAULT_STOP_PCT = 0.08      # סטופ ברירת מחדל: 8% מתחת למחיר הקנייה (כלל O'Neil)
TAKE_PROFIT_PCT = 0.20       # להציע מימוש חלקי מעל 20% רווח

# ---------- בדיקה לאחור ----------
BT_YEARS = 8
BT_MIN_MCAP = 1e9            # כדי שהבדיקה תרוץ מהר – מניות מעל $1B
BT_REBALANCE = 21            # כל כמה ימי מסחר מחליפים את 10 המניות (21 ≈ חודש)
BT_TOP = 10
BT_TRIALS = 400              # כמה צירופי משקלות לנסות בכיול

# ---------- חדר המחקר ----------
RESEARCH_URL = "https://claude.ai/artifact/C2w34x7A5cZLXmqjvMYGzb"   # דף חדר המחקר (פרטי – נפתח רק לך)
# מניות שמודול המחקר עוקב אחריהן – המחירים שלהן נשמרים ב-data/watch_prices.json לחישוב תגובות
WATCH_TICKERS = ["SPY", "QQQ", "IWM", "XLF", "TLT", "NVDA", "AMD", "AVGO", "TSM", "MU", "MSFT", "META", "GOOGL",
                 "AMZN", "ORCL", "INTC", "TSLA", "TEVA", "GM", "CTSH", "PFE", "FSLR", "AA", "CVX", "BTU"]
