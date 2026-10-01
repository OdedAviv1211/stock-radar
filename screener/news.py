"""מה נאמר על המניה: דיווחים רשמיים ל-SEC + כותרות ממקורות מוכרים, וטון השיח מול מצב הגרף.
מקורות:
  1. SEC EDGAR (רשמי, חובת דיווח): 8-K/6-K (אירוע מהותי), 10-Q/10-K (דוחות), Form 4 (עסקאות בעלי עניין).
  2. כותרות מ-Yahoo Finance – רק ממפיצי הודעות רשמיות של החברות או מכלי תקשורת פיננסיים מובילים.
שאר המקורות (בלוגים, פורומים, "המלצות") מסוננים החוצה בכוונה."""
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from .data import log

SEC_UA = {"User-Agent": "stock-radar research tool (github.com/OdedAviv1211/stock-radar) radar-bot@users.noreply.github.com",
          "Accept-Encoding": "gzip, deflate"}

OFFICIAL_WIRES = ["Business Wire", "PR Newswire", "GlobeNewswire", "Accesswire", "ACCESS Newswire"]
TOP_MEDIA = ["Reuters", "Bloomberg", "The Wall Street Journal", "WSJ", "Financial Times", "CNBC", "Barron's",
             "MarketWatch", "Associated Press", "AP", "Investor's Business Daily", "The New York Times", "Fortune",
             "Yahoo Finance", "Axios", "The Information", "Forbes", "Business Insider", "TheStreet", "Benzinga"]

ITEMS_8K = {"1.01": "הסכם מהותי", "1.02": "סיום הסכם מהותי", "2.01": "רכישה/מכירת נכסים", "2.02": "תוצאות כספיות",
            "2.03": "התחייבות פיננסית", "2.05": "התייעלות/פיטורים", "3.02": "הנפקת מניות", "5.02": "שינוי בהנהלה",
            "5.07": "אסיפת בעלי מניות", "7.01": "מצגת/הודעה למשקיעים", "8.01": "אירוע אחר"}
FORMS_HE = {"8-K": "דיווח מיידי", "6-K": "דיווח מיידי (זרה)", "10-Q": "דוח רבעוני", "10-K": "דוח שנתי",
            "4": "עסקת בעל עניין", "S-3": "תשקיף מדף", "424B5": "הנפקה", "SC 13D": "החזקה מהותית", "SC 13G": "החזקה מהותית"}

POS = r"beat|beats|record|surge|soar|jump|rall|upgrade|raise[sd]? (guidance|outlook)|strong|partnership|wins?|award|contract|approv|buyback|outperform|bullish|expand|growth|profit"
NEG = r"miss|plunge|drop|fall|slump|downgrade|cut[s]? (guidance|outlook)|weak|lawsuit|probe|investigat|recall|delay|loss|layoff|dilut|offering|warn|bearish|halt|fraud|short seller|tariff"

_cik = {}


def _cik_map():
    if _cik:
        return _cik
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_UA, timeout=30)
        for v in r.json().values():
            _cik[v["ticker"].upper()] = int(v["cik_str"])
    except Exception as e:  # noqa
        log(f"SEC ticker map failed: {e}")
    return _cik


def sec_filings(t, days=14):
    cik = _cik_map().get(t.replace("-", ".").upper()) or _cik_map().get(t.upper())
    if not cik:
        return []
    try:
        j = requests.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=SEC_UA, timeout=30).json()
    except Exception:  # noqa
        return []
    rec = j.get("filings", {}).get("recent", {})
    cutoff = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
    out, form4 = [], 0
    for i, form in enumerate(rec.get("form", [])):
        d = rec["filingDate"][i]
        if d < cutoff:
            break
        if form == "4":
            form4 += 1
            continue
        if form not in FORMS_HE:
            continue
        items = [x.strip() for x in (rec.get("items", [""] * (i + 1))[i] or "").split(",") if x.strip()]
        what = ", ".join(ITEMS_8K.get(x, x) for x in items if x not in ("9.01",)) if items else ""
        acc = rec["accessionNumber"][i].replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{rec['primaryDocument'][i]}"
        out.append({"date": d, "form": form, "title": FORMS_HE[form] + (f": {what}" if what else ""), "url": url,
                    "src": "SEC", "tone": 0, "official": True})
    if form4:
        out.append({"date": rec["filingDate"][0], "form": "4", "title": f"{form4} דיווחי עסקאות של בעלי עניין (Form 4)",
                    "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4",
                    "src": "SEC", "tone": 0, "official": True})
    return out[:6]


def _tone(title):
    t = title.lower()
    return (1 if re.search(POS, t) else 0) - (1 if re.search(NEG, t) else 0)


def headlines(t, days=7):
    import yfinance as yf
    try:
        raw = yf.Ticker(t).news or []
    except Exception:  # noqa
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for n in raw:
        c = n.get("content") or n
        title = c.get("title") or ""
        prov = (c.get("provider") or {}).get("displayName") if isinstance(c.get("provider"), dict) else c.get("publisher")
        url = ((c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else None) or c.get("link")
        ts = c.get("pubDate") or c.get("providerPublishTime")
        try:
            dt = datetime.fromtimestamp(ts, timezone.utc) if isinstance(ts, (int, float)) else \
                datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:  # noqa
            continue
        if not title or dt < cutoff or not prov:
            continue
        official = any(w.lower() in prov.lower() for w in OFFICIAL_WIRES)
        top = any(m.lower() == prov.lower() or (len(m) > 4 and m.lower() in prov.lower()) for m in TOP_MEDIA)
        if not (official or top):
            continue
        out.append({"date": dt.date().isoformat(), "title": title, "url": url, "src": prov,
                    "tone": _tone(title), "official": official})
    return sorted(out, key=lambda x: x["date"], reverse=True)[:6]


def verdict(items, tech_up):
    """טון השיח (+/-) מול הגרף → מסקנה בשורה אחת."""
    if not items:
        return {"tone": None, "label": "אין פרסומים מהותיים בשבוע האחרון", "conclusion": ""}
    s = sum(i["tone"] for i in items)
    tone = "חיובי" if s > 0 else "שלילי" if s < 0 else "ניטרלי/מעורב"
    if tech_up is None:
        concl = ""
    elif s > 0 and tech_up:
        concl = "השיח והגרף מסכימים – מומנטום נתמך בחדשות"
    elif s < 0 and not tech_up:
        concl = "השיח והגרף מסכימים – חולשה מאושרת, לא לתפוס סכין נופלת"
    elif s > 0 and not tech_up:
        concl = "חדשות טובות אבל הגרף חלש – לחכות לאישור (חזרה מעל ממוצע 20/150)"
    elif s < 0 and tech_up:
        concl = "חדשות שליליות אבל הגרף מחזיק – לעקוב אחרי ממוצע 20 כקו הגנה"
    else:
        concl = "השיח ניטרלי – הגרף קובע"
    return {"tone": tone, "label": f"שיח {tone} ({len(items)} פרסומים)", "conclusion": concl}


def collect(tickers, tech):
    """tech: {טיקר: True אם במגמה עולה}. מחזיר {טיקר: {"items": [...], "verdict": {...}}}."""
    res = {}
    for n, t in enumerate(dict.fromkeys(tickers)):
        items = []
        if not t.endswith(".TA"):
            items += sec_filings(t)
            time.sleep(0.15)  # SEC: עד 10 בקשות לשנייה
        items += headlines(t)
        items.sort(key=lambda x: x["date"], reverse=True)
        res[t] = {"items": items[:8], "verdict": verdict(items, tech.get(t))}
        if n % 10 == 0:
            log(f"news {n}/{len(tickers)}")
    return res
