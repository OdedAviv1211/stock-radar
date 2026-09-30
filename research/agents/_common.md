# כללים משותפים לכל סוכני המחקר

## מקורות – רק רשמיים
מותר (Tier 1 – ראשוני):
- whitehouse.gov (הודעות, צווים, Fact Sheets), חשבון @POTUS / @WhiteHouse ב-X, חשבון Truth Social @realDonaldTrump.
- federalreserve.gov (הודעות FOMC, נאומים, מסיבות עיתונאים), home.treasury.gov.
- sec.gov (8-K, 10-Q, 10-K, Form 4), דפי קשרי משקיעים (Investor Relations) וחדרי חדשות רשמיים של החברות,
  תמלולי שיחות ועידה של דוחות (מהחברה או מתומלל רשמי), נאומים/כנסים רשמיים (GTC, Computex, Tesla Earnings Call).
- חשבונות X/LinkedIn מאומתים של המנכ"לים עצמם (למשל @elonmusk).
מותר בתנאי (Tier 2 – ציטוט של מקור רשמי): Reuters, Bloomberg, CNBC, WSJ, AP, FT – **רק** כשהם מצטטים במפורש
פוסט/נאום/מסמך רשמי. לסמן `source_tier: 2` ולציין מה המקור הרשמי המצוטט.
**אסור:** פורומים, רדיט, "גורמים המעורבים", ערוצי טלגרם/יוטיוב של משפיענים לא מורשים, בלוגים, שמועות, סקירות AI.

## נתוני מחיר
- מחירי סגירה יומיים מ-https://finance.yahoo.com/quote/<TICKER>/history/ (WebFetch).
- תגובה: d0 = ממחיר הסגירה שלפני הפרסום לסגירה ביום המסחר הראשון שאחריו; d5 = חמישה ימי מסחר.
  תמיד לחשב גם מול SPY (או QQQ למניות טכנולוגיה) באותם ימים = "תגובה עודפת".
- אם אין מחיר אמין – לכתוב null, **לא לנחש**.

## לוגיקה
- להבדיל בין "קרה אחרי" לבין "קרה בגלל": לציין אירועים מתחרים באותו יום (דוח, נתון מאקרו, פד).
- כל טענה עם תאריך, קישור וציטוט קצר (עד 25 מילים) או סיכום.
- ביטחון: low / medium / high, עם נימוק.
- לכתוב בעברית, מונחים מקצועיים באנגלית בסוגריים.

## פלט – JSON בלבד בסוף התשובה, בתוך ```json
{
 "agent": "<שם>",
 "period": {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"},
 "events": [{
   "date": "YYYY-MM-DD", "person": "...", "role": "...", "channel": "...", "source_url": "...", "source_tier": 1,
   "summary_he": "...", "quote": "...", "topic": "tariffs|chips|rates|earnings_guidance|product|regulation|other",
   "tickers": ["NVDA"], "expected_direction": "up|down|mixed",
   "reaction": {"NVDA": {"d0": 0.031, "d5": 0.052, "ex_d0": 0.024, "ex_d5": 0.04}},
   "confounders_he": "...", "verdict_he": "האם השוק הגיב בכיוון הצפוי ולמה", "confidence": "medium"
 }],
 "patterns": [{"title_he": "...", "evidence_n": 3, "avg_ex_d0": 0.0, "hit_rate": 0.0, "explanation_he": "...", "confidence": "low"}],
 "upcoming": [{"date": "YYYY-MM-DD", "event_he": "...", "tickers": ["..."], "thesis_he": "...",
   "expected_direction": "up|down|mixed", "confidence": "low", "invalidation_he": "מה יפריך את התזה", "source_url": "..."}]
}
