"""26 שיטות ניתוח – כל שיטה מצביעה בעד (+1) / נייטרלי (0) / נגד (-1). חמש משפחות במשקל שווה + שיטה 26 (שורטים).
בחודש הראשון: מידע בלבד, לא משנה את ציון הרדאר (לפי תוכנית ניהול התיק – גרסה 2)."""
import math

import numpy as np

FAMILIES = ["מגמה", "מומנטום", "תבניות ותזמון", "איכות העסק", "תמחור ושורט"]

# (מספר, שם, משפחה, הסבר קצר למקרא)
METHODS = [
    (1, "תורת דאו", 0, "מגמת השוק הכללי (S&P 500): שוק עולה = רוח גבית"),
    (2, "ניתוח שלבים – Weinstein", 0, "שלב 2 = מגמה עולה מעל ממוצע 150 שעולה; שלב 4 = יורדת"),
    (3, "תבנית המגמה – Minervini", 0, "8 תנאי ממוצעים ומרחק מהשיא/שפל"),
    (4, "חציית ממוצעים 50/200", 0, "ממוצע 50 מעל ממוצע 200 (Golden Cross)"),
    (5, "פריצת דונצ'יאן 55 (הצבים)", 0, "סגירה בשיא של 55 יום"),
    (6, "חוזק יחסי – Levy / RS", 1, "RS 80+ = חזקה מ-80% מהשוק"),
    (7, "מומנטום 12-1 – Jegadeesh & Titman", 1, "תשואת 12 חודשים בלי החודש האחרון"),
    (8, "CAN SLIM – O'Neil", 1, "צמיחה ברווחים ובהכנסות + חוזק יחסי"),
    (9, "רוטציית ענפים", 1, "הענף בין החזקים בשוק"),
    (10, "MACD – Appel", 1, "היסטוגרמת MACD חיובית = מומנטום עולה"),
    (11, "תנועה אחרי דוח (PEAD)", 1, "רווח שצמח + המחיר ממשיך לעלות אחרי הדוח (קירוב)"),
    (12, "התכווצות תנודתיות (VCP)", 2, "תנודות הולכות וקטנות לפני פריצה"),
    (13, "תבניות קלאסיות – Edwards & Magee", 2, "בסיס שטוח/ספל = בעד; ראש וכתפיים = נגד"),
    (14, "וייקוף – איסוף/פיזור", 2, "נפח בימי עלייה מול ימי ירידה"),
    (15, "קופסת דרבס", 2, "פריצה לשיא חדש מתוך טווח צר"),
    (16, "RSI – Wilder", 2, "50–70 בריא; מעל 80 מתוח; מתחת ל-30 חלש"),
    (17, "רצועות בולינגר", 2, "התכווצות ואז פריצה למעלה"),
    (18, "תיקוני פיבונאצ'י", 2, "תיקון של 38%–62% במגמה עולה (משקל נמוך)"),
    (19, "איכות ויתרון תחרותי – Buffett", 3, "תשואה על ההון 15%+ ורווחיות"),
    (20, "ציון פיוטרוסקי (מקוצר)", 3, "רווח, תזרים, נזילות, מרווח, צמיחה, מינוף"),
    (21, "חוסן פיננסי (קירוב ל-Altman Z)", 3, "מזומן מול חוב ויחס שוטף – סיכון קריסה"),
    (22, "רווחיות גולמית – Novy-Marx", 3, "מרווח גולמי גבוה = יתרון תחרותי"),
    (23, "מרווח ביטחון – Graham", 4, "מחיר מול מספר גראהם (רווח × הון עצמי)"),
    (24, "הנוסחה הקסומה – Greenblatt", 4, "תשואת רווח גבוהה + תשואה גבוהה על הנכסים"),
    (25, "צמיחה במחיר סביר – Lynch PEG", 4, "PEG מתחת ל-1.5"),
    (26, "עניין שורט – שינוי חודשי", 4, "שורטיסטים סוגרים = בעד; מגדילים הימור = נגד"),
]


def _n(x):
    try:
        x = float(x)
        return None if math.isnan(x) else x
    except (TypeError, ValueError):
        return None


def evaluate(df, f, row, info, market_level, si=None):
    """df: היסטוריית מחיר; f: אינדיקטורים; row: שורת הרדאר (rs, group, pats, micha); info: נתונים פונדמנטליים."""
    i = info or {}
    v = {}
    c = df["Close"].dropna() if df is not None else None
    h = df["High"].fillna(df["Close"]) if df is not None else None
    lo = df["Low"].fillna(df["Close"]) if df is not None else None
    price = f.get("price")

    def put(n, vote, why):
        v[n] = (vote, why)

    # ---- א. מגמה ----
    put(1, 1 if market_level >= 1 else -1 if market_level <= -1 else 0,
        "השוק במגמה עולה" if market_level >= 1 else "השוק במגמה יורדת" if market_level <= -1 else "השוק בתיקון")
    st = f.get("stage")
    put(2, 1 if st == 2 else -1 if st == 4 else 0, f"שלב {st}")
    ttc = f.get("tt_count") or row.get("tt") or 0
    put(3, 1 if ttc >= 7 else -1 if ttc <= 3 else 0, f"{ttc}/8 תנאים")
    s50, s200 = f.get("sma50"), f.get("sma200")
    if s50 and s200 and not np.isnan(s200):
        put(4, 1 if s50 > s200 else -1, "ממוצע 50 מעל 200" if s50 > s200 else "ממוצע 50 מתחת ל-200")
    else:
        put(4, 0, "אין מספיק היסטוריה")
    if c is not None and len(c) > 56:
        hi55, lo55 = float(h.iloc[-56:-1].max()), float(lo.iloc[-56:-1].min())
        put(5, 1 if price >= hi55 else -1 if price <= lo55 else 0,
            "שיא 55 יום" if price >= hi55 else "שפל 55 יום" if price <= lo55 else "בתוך הטווח")
    else:
        put(5, 0, "אין מספיק היסטוריה")

    # ---- ב. מומנטום ----
    rs = row.get("rs") or 0
    put(6, 1 if rs >= 80 else -1 if rs <= 30 else 0, f"RS {rs}")
    if c is not None and len(c) > 253:
        m121 = float(c.iloc[-22] / c.iloc[-253] - 1)
        put(7, 1 if m121 >= 0.20 else -1 if m121 < 0 else 0, f"{m121 * 100:+.0f}% (12-1)")
    else:
        put(7, 0, "אין מספיק היסטוריה")
    eg, rg = _n(i.get("earningsQuarterlyGrowth")), _n(i.get("revenueGrowth"))
    if eg is not None and rg is not None:
        put(8, 1 if (eg >= 0.25 and rg >= 0.15 and rs >= 80) else -1 if eg < 0 else 0,
            f"רווח {eg * 100:+.0f}% · הכנסות {rg * 100:+.0f}%")
    else:
        put(8, 0, "אין נתוני צמיחה")
    g = row.get("group") or {}
    if g.get("rank") and g.get("of"):
        q = g["rank"] / g["of"]
        put(9, 1 if q <= 0.2 else -1 if q >= 0.8 else 0, f"ענף במקום {g['rank']} מתוך {g['of']}")
    else:
        put(9, 0, "אין דירוג ענף")
    mh = _n(f.get("macd_hist"))
    put(10, 0 if mh is None else (1 if mh > 0 else -1), "היסטוגרמה חיובית" if (mh or 0) > 0 else "היסטוגרמה שלילית")
    r21 = _n(f.get("r21")) or 0
    if eg is not None:
        put(11, 1 if (eg > 0.15 and r21 > 0) else -1 if (eg < 0 and r21 < 0) else 0,
            f"רווח רבעוני {eg * 100:+.0f}%, חודש {r21 * 100:+.0f}%")
    else:
        put(11, 0, "אין נתוני דוח")

    # ---- ג. תבניות ותזמון ----
    pats = " ".join(p.get("name", "") for p in (row.get("pats") or []))
    put(12, 1 if ("VCP" in pats or "התכווצות" in pats) else 0, "התכווצות תנודתיות" if ("VCP" in pats or "התכווצות" in pats) else "לא זוהתה")
    hs = "ראש וכתפיים" in pats or bool((row.get("micha") or {}).get("hs"))
    base = any(k in pats for k in ("בסיס", "ספל", "דגל", "שטוח"))
    put(13, -1 if hs else 1 if base else 0, "ראש וכתפיים" if hs else "בסיס/ספל" if base else "אין תבנית")
    ud = _n(f.get("updown"))
    put(14, 0 if ud is None else (1 if ud >= 1.3 else -1 if ud <= 0.8 else 0), f"יחס נפח עלייה/ירידה {ud:.1f}" if ud else "—")
    dh = _n(f.get("dist_hi")) or 0
    put(15, 1 if (f.get("new_high") or f.get("breakout")) else -1 if dh < -0.30 else 0,
        "פריצה לשיא" if (f.get("new_high") or f.get("breakout")) else f"{dh * 100:.0f}% מהשיא")
    rsi = _n(f.get("rsi"))
    put(16, 0 if rsi is None else (-1 if rsi > 80 or rsi < 30 else 1 if 50 <= rsi <= 70 else 0), f"RSI {rsi:.0f}" if rsi else "—")
    if c is not None and len(c) > 140:
        m = c.rolling(20).mean()
        sd = c.rolling(20).std()
        bw = (4 * sd / m).dropna()
        up, dn = float((m + 2 * sd).iloc[-1]), float((m - 2 * sd).iloc[-1])
        squeeze = float(bw.iloc[-6:].min()) <= float(bw.iloc[-126:].quantile(0.2))
        put(17, 1 if (squeeze and price > up) else -1 if price < dn else 0,
            "פריצה אחרי התכווצות" if (squeeze and price > up) else "מתחת לרצועה התחתונה" if price < dn else "בתוך הרצועות")
        hh, ll = float(h.iloc[-60:].max()), float(lo.iloc[-60:].min())
        retr = (hh - price) / (hh - ll) if hh > ll else 0
        put(18, 1 if (st == 2 and 0.38 <= retr <= 0.62) else -1 if retr > 0.786 else 0, f"תיקון {retr * 100:.0f}% מהגל האחרון")
    else:
        put(17, 0, "אין מספיק היסטוריה")
        put(18, 0, "אין מספיק היסטוריה")

    # ---- ד. איכות העסק ----
    roe, pm = _n(i.get("returnOnEquity")), _n(i.get("profitMargins"))
    if roe is not None:
        put(19, 1 if (roe >= 0.15 and (pm or 0) > 0) else -1 if roe < 0 else 0, f"ROE {roe * 100:.0f}%")
    else:
        put(19, 0, "אין נתונים")
    roa, ocf, ni = _n(i.get("returnOnAssets")), _n(i.get("operatingCashflow")), _n(i.get("netIncomeToCommon"))
    cr, gm, de = _n(i.get("currentRatio")), _n(i.get("grossMargins")), _n(i.get("debtToEquity"))
    checks = [roa is not None and roa > 0, ocf is not None and ocf > 0, ocf is not None and ni is not None and ocf > ni,
              cr is not None and cr > 1, gm is not None and gm > 0.3, rg is not None and rg > 0, de is not None and de < 100]
    known = sum(1 for x in (roa, ocf, cr, gm, rg, de) if x is not None)
    if known >= 4:
        sc = sum(checks)
        put(20, 1 if sc >= 5 else -1 if sc <= 2 else 0, f"{sc}/7")
    else:
        put(20, 0, "אין מספיק נתונים")
    cash, debt = _n(i.get("totalCash")), _n(i.get("totalDebt"))
    if cash is not None and debt is not None:
        strong = cash >= debt or (cr or 0) >= 1.5
        weak = (de or 0) > 200 and (cr or 2) < 1
        put(21, 1 if strong else -1 if weak else 0, "קופה חזקה" if strong else "מינוף גבוה ונזילות נמוכה" if weak else "בינוני")
    else:
        put(21, 0, "אין נתונים")
    put(22, 0 if gm is None else (1 if gm >= 0.5 else -1 if gm < 0.2 else 0), f"מרווח גולמי {gm * 100:.0f}%" if gm is not None else "—")

    # ---- ה. תמחור ושורט ----
    eps, bv = _n(i.get("trailingEps")), _n(i.get("bookValue"))
    if eps and bv and eps > 0 and bv > 0 and price:
        gn = math.sqrt(22.5 * eps * bv)
        put(23, 1 if price < gn else -1 if price > 2 * gn else 0, f"מספר גראהם {gn:.0f} מול מחיר {price:.0f}")
    else:
        put(23, 0 if (eps or 0) >= 0 else -1, "הפסדית" if (eps or 0) < 0 else "אין נתונים")
    ebitda, ev = _n(i.get("ebitda")), _n(i.get("enterpriseValue"))
    if ebitda and ev and ev > 0:
        ey = ebitda / ev
        put(24, 1 if (ey >= 0.08 and (roa or 0) >= 0.10) else -1 if ey < 0.02 else 0, f"תשואת רווח {ey * 100:.1f}%")
    else:
        put(24, 0, "אין נתונים")
    peg = _n(i.get("trailingPegRatio"))
    put(25, 0 if peg is None or peg <= 0 else (1 if peg < 1.5 else -1 if peg > 3 else 0), f"PEG {peg:.1f}" if peg else "—")
    s = si or {}
    put(26, s.get("vote", 0), s.get("txt", "אין נתונים"))

    fam = {k: [] for k in FAMILIES}
    for n, name, fi, _ in METHODS:
        vote, why = v.get(n, (0, "—"))
        fam[FAMILIES[fi]].append({"n": n, "name": name, "vote": vote, "why": why})
    pro = sum(1 for x in v.values() if x[0] > 0)
    con = sum(1 for x in v.values() if x[0] < 0)
    by = {k: {"pro": sum(1 for m in L if m["vote"] > 0), "con": sum(1 for m in L if m["vote"] < 0), "n": len(L)} for k, L in fam.items()}
    index = sum((b["pro"] - b["con"]) / b["n"] for b in by.values()) / len(by)      # -1..+1, משקל שווה למשפחה
    return {"pro": pro, "con": con, "n": len(METHODS), "index": round(index, 3), "by": by, "fam": fam}
