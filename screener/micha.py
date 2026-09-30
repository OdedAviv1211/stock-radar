"""6 השיטות של מיכה סטוקס (מתוך הסרטון הרשמי "6 שיטות השקעה שכל משקיע חייב להכיר", ערוץ Micha.Stocks):
1. בסיס – ממוצע נע ארוך (MA 150/200): קונים רק כשהמחיר מעל הממוצע הארוך. מערכת הסינון הראשונית.
2. תזמון – ממוצע נע קצר (MA 20/50): קנייה כשהמחיר מתקן אל הממוצע הקצר בתוך מגמה עולה,
   או כשהממוצע הקצר חוצה את הארוך.
3. מפה – תמיכות והתנגדויות: קנייה בקרבת תמיכה, מכירה בקרבת התנגדות.
4. כיוון – קו מגמה: חיבור שפלים עולים; קנייה בנגיעה בקו, מכירה בשבירתו.
5. קריאה – תצורות (כוס וידית, ראש וכתפיים): נותנות יעד מחיר אחרי פריצה (Take Profit).
6. פיבונאצ'י – "אזור הזהב" 50%–61.8% בתיקון בתוך מגמה.
המסר המרכזי שלו: עקביות בשיטה אחת. כאן כל שיטה נבדקת בנפרד ומוצגת כצ'ק-ליסט – לא מחליפה את שיקול הדעת."""
import numpy as np

NAMES = ["ממוצע ארוך 150/200", "ממוצע קצר 20/50", "תמיכה/התנגדות", "קו מגמה", "תצורה", "פיבונאצ'י"]


def _swings(arr, k=5, lows=True):
    idx = []
    for i in range(k, len(arr) - k):
        w = arr[i - k:i + k + 1]
        if (lows and arr[i] == w.min()) or (not lows and arr[i] == w.max()):
            idx.append(i)
    return idx


def _levels(points, tol=0.02):
    """מקבץ נקודות מפנה לרמות מחיר; מחזיר [(רמה, מספר נגיעות)]."""
    out = []
    for p in sorted(points):
        if out and abs(p / out[-1][0] - 1) <= tol:
            lvl, n = out[-1]
            out[-1] = ((lvl * n + p) / (n + 1), n + 1)
        else:
            out.append((p, 1))
    return out


def head_shoulders(h, c):
    """ראש וכתפיים (תבנית היפוך מסוכנת): שלושה שיאים, האמצעי הגבוה, הכתפיים ברמה דומה, המחיר מתחת לקו הצוואר."""
    n = len(c)
    if n < 90:
        return None
    seg = h[-120:]
    off = n - len(seg)
    pk = _swings(seg, 6, lows=False)
    if len(pk) < 3:
        return None
    a, b, d = pk[-3], pk[-2], pk[-1]
    if not (seg[b] > seg[a] * 1.03 and seg[b] > seg[d] * 1.03 and abs(seg[a] / seg[d] - 1) < 0.06):
        return None
    neck = min(c[off + a:off + b].min(), c[off + b:off + d].min())
    if c[-1] < neck:
        return {"name": "ראש וכתפיים", "neck": float(neck), "target": float(neck - (seg[b] - neck))}
    return None


def analyze(df, pats=None):
    """מחזיר {"score": 0-6, "checks":[{"name","ok","note"}], "hs": ראש וכתפיים או None, "target": יעד מתצורה או None}."""
    df = df.dropna(subset=["Close"]).iloc[-260:]
    c = df["Close"].values.astype(float)
    h = df["High"].fillna(df["Close"]).values.astype(float)
    l = df["Low"].fillna(df["Close"]).values.astype(float)
    n = len(c)
    if n < 210:
        return None
    price = c[-1]
    ma = lambda k, end=None: float(np.mean(c[(n if end is None else end) - k:(n if end is None else end)]))
    s20, s50, s150, s200 = ma(20), ma(50), ma(150), ma(200)
    s150_prev = ma(150, n - 20)
    checks = []

    # 1. ממוצע ארוך
    ok1 = price > s150 and price > s200 and s150 > s150_prev
    checks.append({"name": NAMES[0], "ok": ok1,
                   "note": "מעל 150 ו-200, והממוצע עולה" if ok1 else ("מתחת לממוצע הארוך – מחוץ למשחק" if price < s150 else "הממוצע הארוך לא עולה")})

    # 2. ממוצע קצר: תיקון לממוצע 20/50 בתוך מגמה, או חצייה של 50 מעל 150 ב-20 הימים האחרונים
    near20 = 0 <= price / s20 - 1 <= 0.03
    near50 = 0 <= price / s50 - 1 <= 0.03
    cross = any(ma(50, n - i) > ma(150, n - i) and ma(50, n - i - 1) <= ma(150, n - i - 1) for i in range(0, 20))
    ok2 = ok1 and (near20 or near50 or cross)
    note2 = ("חצייה של ממוצע 50 מעל 150" if cross else "תיקון לממוצע 20" if near20 else "תיקון לממוצע 50" if near50
             else ("מתחת לממוצע 20" if price < s20 else f"רחוק מהממוצע הקצר ({(price / s20 - 1) * 100:+.0f}% מ-20)"))
    checks.append({"name": NAMES[1], "ok": ok2, "note": note2})

    # 3. תמיכה / התנגדות
    lows = [l[i] for i in _swings(l, 5, True)]
    highs = [h[i] for i in _swings(h, 5, False)]
    sup = [lv for lv, k in _levels(lows) if lv < price and k >= 2]
    res = [lv for lv, k in _levels(highs) if lv > price and k >= 2]
    support = max(sup) if sup else None
    resist = min(res) if res else None
    broke = any(0 <= price / lv - 1 <= 0.03 for lv, k in _levels(highs) if k >= 2 and lv <= price)
    near_sup = support is not None and price / support - 1 <= 0.05
    room = resist is None or resist / price - 1 >= 0.08
    ok3 = (near_sup and room) or broke
    note3 = ("פרצה מעל התנגדות – ההתנגדות הופכת לתמיכה" if broke else
             f"קרוב לתמיכה {support:.2f}" if near_sup and room else
             f"התנגדות קרובה {resist:.2f}" if resist and not room else "לא ליד תמיכה")
    checks.append({"name": NAMES[2], "ok": ok3, "note": note3, "support": support, "resistance": resist})

    # 4. קו מגמה על שפלים עולים (120 ימים)
    li = [i for i in _swings(l, 5, True) if i >= n - 120]
    ok4, note4, line_now = False, "אין מספיק שפלים לקו מגמה", None
    if len(li) >= 3:
        x = np.array(li, float)
        y = np.array([l[i] for i in li])
        slope, icpt = np.polyfit(x, y, 1)
        line_now = slope * (n - 1) + icpt
        if slope > 0:
            gap = price / line_now - 1
            if 0 <= gap <= 0.04:
                ok4, note4 = True, "נוגעת בקו מגמה עולה – נקודת כניסה"
            elif gap < -0.02:
                note4 = "שברה את קו המגמה העולה – סימן מכירה"
            else:
                note4 = f"מעל קו מגמה עולה ({gap * 100:.0f}% מעליו)"
        else:
            note4 = "קו המגמה יורד"
    checks.append({"name": NAMES[3], "ok": ok4, "note": note4})

    # 5. תצורות (מהזיהוי הקיים) + יעד מחיר
    target = None
    near = [p for p in (pats or []) if -0.05 <= p["dist"] <= 0.03]
    if near:
        target = near[0].get("target")
    ok5 = bool(near)
    hs = head_shoulders(h, c)
    note5 = (f"{near[0]['name']} סמוך לפריצה" + (f", יעד {target:.2f}" if target else "")) if ok5 else \
        ("ראש וכתפיים – תבנית היפוך שלילית" if hs else "אין תצורה פעילה")
    checks.append({"name": NAMES[4], "ok": ok5 and not hs, "note": note5})

    # 6. פיבונאצ'י: תיקון 50%–61.8% מהגל האחרון, בתוך מגמה עולה
    j = n - 120 + int(np.argmax(h[-120:]))
    lo_seg = l[max(0, j - 120):j + 1]
    ok6, note6 = False, "אין תיקון מתאים"
    if len(lo_seg) > 10:
        sw_lo, sw_hi = float(lo_seg.min()), float(h[j])
        if sw_hi > sw_lo * 1.15 and j < n - 3:
            r = (sw_hi - price) / (sw_hi - sw_lo)
            ok6 = ok1 and 0.5 <= r <= 0.65
            note6 = f"תיקון של {r * 100:.0f}% מהגל" + (" – באזור הזהב" if ok6 else "")
        elif j >= n - 3:
            note6 = "בשיא – אין תיקון"
    checks.append({"name": NAMES[5], "ok": ok6, "note": note6})

    return {"score": int(sum(ch["ok"] for ch in checks)), "checks": checks, "hs": hs, "target": target,
            "line": line_now}
