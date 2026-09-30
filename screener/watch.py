"""רשימת מעקב ממוקדת לפי תחומים – התראות "בדחיפה" לפי תנועת המניה.
הלב: ממוצע 20 של מיכה סטוקס (תזמון) בתוך הפילטר של ממוצע 150 (מגמה), ועוד 5 השיטות האחרות כצ'ק-ליסט.
כל אירוע מקבל דחיפות: 3 = מיידי (שבירה/פריצה), 2 = חשוב, 1 = מידע."""
import csv
import os

import numpy as np

from . import micha, patterns

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIG_MOVE = 0.05        # תנועה יומית שמצדיקה התראה
VOL_SURGE = 1.5        # נפח ביחס לממוצע 50
EXTENDED_20 = 0.15     # מתיחות מעל ממוצע 20 – לא לרדוף


def load_watchlist(path=None):
    path = path or os.path.join(ROOT, "watchlist.csv")
    if not os.path.exists(path):
        return []
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8")) if (r.get("ticker") or "").strip()]
    for r in rows:
        r["ticker"] = r["ticker"].strip().upper()
    return rows


def _sma(c, k, back=0):
    end = len(c) - back
    return float(np.mean(c[end - k:end]))


def evaluate(df):
    """מחזיר מצב מלא למניה: מחירים, ממוצעים, אירועים, המלצה ורמות."""
    df = df.dropna(subset=["Close"])
    if len(df) < 210:
        return None
    c = df["Close"].values.astype(float)
    l = df["Low"].fillna(df["Close"]).values.astype(float)
    v = df["Volume"].fillna(0).values.astype(float)
    p, p0 = c[-1], c[-2]
    s20, s20p = _sma(c, 20), _sma(c, 20, 1)
    s50, s50p = _sma(c, 50), _sma(c, 50, 1)
    s150, s150p, s150m = _sma(c, 150), _sma(c, 150, 1), _sma(c, 150, 20)
    s200 = _sma(c, 200)
    chg = p / p0 - 1
    vr = v[-1] / max(1.0, v[-51:-1].mean())
    up = p > s150 and s150 > s150m
    d20 = p / s20 - 1
    max_d20_10 = max(c[-11:-1] / np.array([_sma(c, 20, i) for i in range(1, 11)]) - 1)
    pats = patterns.detect(df)
    m = micha.analyze(df, pats) or {"score": 0, "checks": [], "hs": None}
    ev = []

    def add(u, key, text):
        ev.append({"u": u, "key": key, "text": text})

    # ממוצע 20 – התזמון של מיכה
    if p0 < s20p and p > s20:
        add(2 if up else 1, "x20up", "חזרה מעל ממוצע 20" + (" בתוך מגמה עולה – אות כניסה/הוספה" if up else " אבל מתחת ל-150 – תיקון במגמת ירידה, לא לקנות"))
    if p0 > s20p and p < s20:
        add(2 if up else 1, "x20dn", "ירדה מתחת לממוצע 20" + (" – להדק סטופ / לצמצם חלקית" if up else ""))
    if up and 0 <= d20 <= 0.02 and max_d20_10 >= 0.05:
        add(2, "pb20", f"תיקון לממוצע 20 ({s20:.2f}) אחרי עלייה – נקודת הכניסה המועדפת בשיטת מיכה")
    if d20 > EXTENDED_20:
        add(1, "ext20", f"מתוחה {d20 * 100:.0f}% מעל ממוצע 20 – לא לרדוף; לשקול מימוש חלקי")
    # ממוצעים ארוכים – שבירות
    if p0 > s50p and p < s50:
        add(3 if up else 2, "x50dn", f"שברה את ממוצע 50 ({s50:.2f})")
    if p0 < s50p and p > s50:
        add(2, "x50up", f"פרצה מעל ממוצע 50 ({s50:.2f})")
    if p0 > s150p and p < s150:
        add(3, "x150dn", f"שברה את ממוצע 150 ({s150:.2f}) – יציאה לפי הכלל הבסיסי")
    if p0 < s150p and p > s150:
        add(3, "x150up", f"חזרה מעל ממוצע 150 ({s150:.2f}) – תחילת מגמה אפשרית, לחכות לאישור")
    # תנועה חריגה
    if abs(chg) >= BIG_MOVE:
        add(3 if vr >= VOL_SURGE else 2, "big" + ("up" if chg > 0 else "dn"),
            f"תנועה של {chg * 100:+.1f}% היום" + (f" בנפח פי {vr:.1f} מהממוצע" if vr >= VOL_SURGE else ""))
    # תצורות, פריצה, קו מגמה, ראש וכתפיים
    for pt in pats:
        if p0 <= pt["pivot"] < p:
            add(3, "brk", f"פריצה מתבנית {pt['name']} מעל {pt['pivot']:.2f}" + (f", יעד {pt['target']:.2f}" if pt.get("target") else ""))
    # קו מגמה וראש-וכתפיים הם מצבים – מתריעים רק ביום שבו הם נוצרו
    mp = micha.analyze(df.iloc[:-1], patterns.detect(df.iloc[:-1])) or {"checks": [], "hs": None}
    broken = lambda mm: any(ch["name"] == micha.NAMES[3] and "שברה" in ch["note"] for ch in mm["checks"])
    if broken(m) and not broken(mp):
        add(2, "tl", "שבירת קו מגמה עולה")
    if m.get("hs") and not mp.get("hs"):
        add(3, "hs", f"ראש וכתפיים – מתחת לקו הצוואר {m['hs']['neck']:.2f}")

    # המלצה
    low10 = float(l[-10:].min())
    stop = max(min(s20 * 0.97, low10 * 0.99), p * 0.92) if up else None
    if any(e["key"] in ("x150dn", "hs") for e in ev):
        act, lvl = "יציאה", 3
    elif not up and p < s150:
        act, lvl = ("לא להחזיק – מתחת ל-150 ול-200", 3) if p < s200 else ("המתנה – מתחת ל-150", 2)
    elif any(e["key"] in ("x50dn", "tl") for e in ev):
        act, lvl = "צמצום / הידוק סטופ", 2
    elif any(e["key"] in ("pb20", "brk") for e in ev) or (any(e["key"] == "x20up" for e in ev) and up):
        act, lvl = "קנייה / הוספה", 0
    elif d20 > EXTENDED_20:
        act, lvl = "החזקה – לא להוסיף", 1
    elif up and d20 >= 0:
        act, lvl = "החזקה", 1
    elif up:
        act, lvl = "המתנה – מתחת ל-20, מעל 150", 1
    else:
        act, lvl = "המתנה", 1
    tgt = m.get("target")
    return {
        "price": p, "chg": chg, "vol_ratio": vr, "sma20": s20, "sma50": s50, "sma150": s150, "sma200": s200,
        "d20": d20, "d50": p / s50 - 1, "d150": p / s150 - 1, "uptrend": up, "micha": m["score"],
        "micha_checks": [{"name": ch["name"], "ok": ch["ok"], "note": ch["note"]} for ch in m["checks"]],
        "pats": [{"name": x["name"], "pivot": x["pivot"], "target": x.get("target")} for x in pats],
        "events": sorted(ev, key=lambda e: -e["u"]), "action": act, "level": lvl,
        "entry": s20 if up and d20 > 0.03 else p, "stop": stop,
        "target": tgt if tgt and tgt > p else (p * (1 + 3 * (1 - stop / p)) if stop else None),
    }


def order_ticket(t, ev, account=None, risk_pct=0.01):
    """טיוטת פקודה לביצוע ידני – Claude לא שולח פקודות בעצמו."""
    if not ev or ev["level"] != 0 or not ev["stop"]:
        return None
    entry, stop = ev["entry"], ev["stop"]
    qty = int(account * risk_pct / (entry - stop)) if account and entry > stop else None
    return {"t": t, "side": "BUY", "type": "LIMIT", "limit": round(entry * 1.003, 2), "stop": round(stop, 2),
            "target": round(ev["target"], 2) if ev["target"] else None, "qty": qty}
