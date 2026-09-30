"""ניקוד משולב והסברים בעברית."""
import numpy as np

from . import config


def _clip01(x):
    return float(min(1.0, max(0.0, x))) if x is not None and not np.isnan(x) else None


def rs_ratings(feats, groups):
    """RS Rating 1-99 בסגנון IBD, מחושב בנפרד לכל שוק (ארה"ב / ת"א)."""
    out = {}
    for tickers in groups:
        vals = [(t, feats[t]["rs_raw"]) for t in tickers if t in feats and not np.isnan(feats[t]["rs_raw"])]
        if not vals:
            continue
        arr = np.array([v for _, v in vals])
        for t, v in vals:
            out[t] = int(round(1 + 98 * (arr < v).sum() / max(1, len(arr) - 1)))
    return out


def trend_score(f, rs):
    cnt = f["tt_count"] + (1 if rs >= 70 else 0)
    s = cnt / 8 * 85
    if f["stage"] == 2:
        s += 15
    elif f["stage"] == 4:
        s -= 20
    return max(0.0, min(100.0, s)), cnt


def accum_score(f):
    a = _clip01((f["updown"] - 0.7) / 1.1) or 0
    b = _clip01((f["vol_surge"] - 0.8) / 1.0) or 0
    return 100 * (0.7 * a + 0.3 * b)


def setup_score(f):
    dp = f["dist_pivot"]
    if -0.06 <= dp <= 0.03:
        p = 1.0
    elif dp < -0.06:
        p = max(0.0, 1 - (-0.06 - dp) / 0.2)
    else:
        p = max(0.35, 1 - (dp - 0.03) / 0.15)
    t = _clip01((1.1 - f["vol_contract"]) / 0.6) or 0
    e = 1.0 if f["ext_sma50"] < 0.15 else max(0.0, 1 - (f["ext_sma50"] - 0.15) / 0.25)
    s = 100 * (0.5 * p + 0.3 * t + 0.2 * e)
    if f["breakout"]:
        s = min(100, s + 10)
    return s


def fund_score(info):
    if not info:
        return 50.0, False
    rg = info.get("revenueGrowth")
    eg = info.get("earningsQuarterlyGrowth") if info.get("earningsQuarterlyGrowth") is not None else info.get("earningsGrowth")
    gm, roe = info.get("grossMargins"), info.get("returnOnEquity")
    parts = []
    if rg is not None:
        parts.append((0.35, _clip01(rg / 0.40)))
    if eg is not None:
        parts.append((0.35, _clip01(eg / 0.50)))
    if gm is not None:
        parts.append((0.15, _clip01((gm - 0.20) / 0.50)))
    if roe is not None:
        parts.append((0.15, _clip01(roe / 0.30)))
    parts = [(w, x) for w, x in parts if x is not None]
    if not parts:
        return 50.0, False
    return 100 * sum(w * x for w, x in parts) / sum(w for w, _ in parts), True


W = dict(config.WEIGHTS)  # המשקלות הפעילים (ייתכן שמכוילים מהבדיקה לאחור)


def composite(parts, weights=None):
    w = weights or W
    return sum(w[k] * parts.get(k, 50.0) for k in w)


def pattern_bonus(pats):
    """בונוס למבנה: תבנית קלאסית כשהמחיר עד 5% מתחת לפיבוט או עד 3% מעליו."""
    return 12.0 if any(-0.05 <= p["dist"] <= 0.03 for p in pats) else (5.0 if pats else 0.0)


def days_to_earnings(info, now_ts):
    if not info:
        return None
    ts = info.get("earningsTimestampStart") or info.get("earningsTimestamp")
    if not ts:
        return None
    d = (float(ts) - now_ts) / 86400
    return int(np.ceil(d)) if d >= -0.5 else None


def pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def reasons(f, rs, tt_cnt, info, analog, sim, pats=None, group=None, earn_days=None):
    """רשימת נימוקים (חיוביים) ואזהרות – בעברית."""
    good, warn = [], []
    first = []
    for p in pats or []:
        where = "סמוך לנקודת הפריצה" if -0.05 <= p["dist"] <= 0.03 else ("כבר פרצה" if p["dist"] > 0.03 else "עדיין בבנייה")
        first.append(f"תבנית {p['name']} ({p['detail']}) – {where}, פיבוט {p['pivot']:.2f}")
    if group and group.get("rank_pct") is not None:
        if group["rank_pct"] >= 80:
            first.append(f"הענף ({group['name']}) בין 20% החזקים בשוק – מקום {group['rank']} מתוך {group['of']}")
        elif group["rank_pct"] < 40:
            warn.append(f"הענף ({group['name']}) חלש – מקום {group['rank']} מתוך {group['of']}")
    if earn_days is not None and earn_days <= config.EARNINGS_WARN_DAYS:
        warn.append(f"דוח רבעוני בעוד {max(0, earn_days)} ימים – סיכון לגאפ; לשקול להמתין לאחרי הדוח")
    if f["stage"] == 2:
        good.append(f"מעל ממוצע 150 העולה ({pct(f['ext_sma150'])} מעליו) – שלב 2 לפי Weinstein")
    elif f["stage"] in (1, 3):
        warn.append(f"ממוצע 150 שטוח – שלב {f['stage']} (לא מגמה עולה מובהקת)")
    else:
        warn.append("מתחת לממוצע 150 היורד – שלב 4")
    good.append(f"עומדת ב-{tt_cnt}/8 קריטריוני Trend Template של Minervini") if tt_cnt >= 6 else \
        warn.append(f"רק {tt_cnt}/8 קריטריוני Trend Template")
    if rs >= 80:
        good.append(f"חוזק יחסי RS {rs} – חזקה מ-{rs}% מהשוק")
    good.extend(first)
    if f["dist_hi"] >= -0.05:
        good.append("קרובה לשיא 52 שבועות (פחות מ-5%) – אין התנגדות מעל")
    elif f["dist_hi"] < -0.25:
        warn.append(f"{pct(-f['dist_hi'])} מתחת לשיא השנתי")
    if f["breakout"]:
        good.append("פריצה מעל פיבוט 60 יום בנפח גבוה מהממוצע")
    elif -0.06 <= f["dist_pivot"] <= 0:
        good.append(f"במרחק {pct(-f['dist_pivot'], 1)} מנקודת פריצה (פיבוט {f['pivot']:.2f})")
    if f["vol_contract"] < 0.75:
        good.append("התכווצות תנודתיות (VCP) – מבנה טיפוסי לפני פריצה")
    if f["updown"] >= 1.3:
        good.append(f"איסוף מוסדי: נפח בימי עלייה פי {f['updown']:.1f} מימי ירידה (50 יום)")
    elif f["updown"] < 0.85:
        warn.append("נפח בימי ירידה גבוה מימי עלייה – חלוקה")
    if info:
        rg = info.get("revenueGrowth")
        eg = info.get("earningsQuarterlyGrowth")
        if rg is not None and rg >= 0.20:
            good.append(f"צמיחה בהכנסות {pct(rg)} (שנתי, רבעון אחרון)")
        if eg is not None and eg >= 0.25:
            good.append(f"צמיחה ברווח הרבעוני {pct(eg)}")
        if rg is not None and rg < 0:
            warn.append(f"הכנסות יורדות ({pct(rg)})")
        spf = info.get("shortPercentOfFloat")
        if spf and spf > 0.15:
            warn.append(f"שורט גבוה ({pct(spf)} מהמניות הצפות) – תנודתיות גבוהה")
    if analog and sim >= 55:
        good.append(f"דמיון {sim:.0f}% ל{analog['label']} (עלתה {pct(analog['fwd12'])} בשנה שאחרי)")
    if f["ext_sma50"] > 0.25:
        warn.append(f"מתוחה: {pct(f['ext_sma50'])} מעל ממוצע 50 – עדיף להמתין לתיקון/בסיס")
    if f["rsi"] > 78:
        warn.append(f"RSI {f['rsi']:.0f} – קנויית יתר בטווח הקצר")
    if f["atr_pct"] > 0.06:
        warn.append(f"תנודתיות יומית גבוהה (ATR {pct(f['atr_pct'], 1)})")
    return good, warn


def trade_plan(f, mc=None):
    """רעיון כניסה/יציאה בגישת O'Neil/Minervini – סטופ 7-8% או מתחת לשפל 10 ימים."""
    price = f["price"]
    entry = f["pivot"] if f["dist_pivot"] < 0 else price
    stop = max(f["low10"] * 0.99, entry * 0.92)
    stop = min(stop, entry * 0.97)
    risk = 1 - stop / entry
    tgt = mc.get("target") if mc else None
    return {"entry": entry, "stop": stop, "risk": risk, "target1": tgt if tgt and tgt > entry else entry * (1 + 3 * risk),
            "target_src": "יעד התצורה" if tgt and tgt > entry else "יעד 3R",
            "mode": "כניסה בפריצה מעל הפיבוט" if f["dist_pivot"] < 0 else "כבר מעל הפיבוט – כניסה בתיקון/המשך"}
