"""שליחת סיכום בוקר לטלגרם מתוך data/latest.json.
צריך שני Secrets במאגר: TELEGRAM_TOKEN (מ-@BotFather) ו-TELEGRAM_CHAT_ID (מ-@userinfobot).
אופציונלי: DASHBOARD_URL (אחרת נבנה אוטומטית מכתובת המאגר)."""
import html
import json
import os
import sys
from datetime import datetime, timezone

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))


def pct(x, d=1):
    return "—" if x is None else f"{'+' if x >= 0 else ''}{x * 100:.{d}f}%"


def build(rep, url):
    e = html.escape
    lines = [f"📈 <b>הדוח היומי</b> · סגירה {e(rep['asof'])}"]
    gen = rep.get("generated", "")
    try:
        age_h = (datetime.now(timezone.utc) - datetime.strptime(gen, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)).total_seconds() / 3600
    except ValueError:
        age_h = 0
    if age_h > 30:
        lines.append(f"⚠️ הדוח לא התעדכן מאז {e(gen)} – כנראה שהריצה הלילית נכשלה (לבדוק בלשונית Actions).")
    top_links = [f'🔗 <a href="{e(url)}">הדוח המלא באתר ←</a>']
    if rep.get("research_url"):
        top_links.append(f'🔬 <a href="{e(rep["research_url"])}">חדר המחקר ←</a>')
    lines.append(" · ".join(top_links))
    ex_ = rep.get("exec") or []
    if ex_:
        dot = {3: "🔴", 2: "🟠", 1: "🔵", 0: "🟢"}
        lines += ["", "<b>━━ קציר מנהלים ━━</b>"] + [f"{dot.get(x['lv'], '•')} <b>{e(x['k'])}:</b> {e(x['t'])}" for x in ex_]
    news = rep.get("news", {})
    tone = lambda t: {"חיובי": " 🟢שיח", "שלילי": " 🔴שיח"}.get((news.get(t, {}).get("verdict") or {}).get("tone"), "")

    # ===== 1. התיקים שלי =====
    lines += ["", "<b>━━ 1 · התיקים שלי ━━</b>"]
    g = rep.get("goal")
    if g:
        lines.append(f"🎯 יעד ₪{g['cfg']['monthly_net_ils']:,}/חודש: <b>{e(g['status'])}</b> "
                     f"(₪{g['current_ils']:,.0f} מול תוכנית ₪{g['planned_ils']:,.0f}) · "
                     f"{g['progress_a'] * 100:.1f}% מהיעד · ~{g['base_years'] if g['base_years'] is not None else '80+'} שנים בהפקדה ₪{g['cfg']['monthly_contrib_ils']:,}")
    by, accts = {}, {}
    for p in rep.get("portfolio", []):
        by.setdefault(p["t"], []).append(p)
        accts.setdefault(p.get("acct") or p.get("notes") or "תיק", []).append(p)
    for an, lst in accts.items():
        lst = sorted(lst, key=lambda x: -(x.get("level") or 0))
        act = [p for p in lst if (p.get("level") or 0) >= 2]
        add = [p["t"] for p in lst if p.get("action") == "אזור הוספה"]
        lines += ["", f"<b>💼 {e(an)}</b> · {len(lst)} מניות"]
        if add:
            lines.append("➕ אזור הוספה: " + ", ".join(e(t) for t in add))
        for p in act[:6]:
            lines.append(f"{'🔴' if p['level'] >= 3 else '🟠'} <b>{e(p['t'])}</b> {e(p.get('action', ''))} – {e(p['signals'][0])}{tone(p['t'])}")
        ok = [p["t"] for p in lst if (p.get("level") or 0) < 2 and p["t"] not in add]
        if ok:
            lines.append("🟢 להחזיק: " + ", ".join(e(t) for t in ok))

    # ===== 2. ניתוח יומי =====
    lines += ["", "<b>━━ 2 · ניתוח יומי ━━</b>",
              " · ".join(f"{e(r['name'].split(' (')[0])}: {e(r['status'])}" for r in rep["regime"])]
    ev = [w for w in rep.get("watch", []) if any(x.get("u", 0) >= 2 for x in w.get("events", []))]
    if ev:
        lines.append("<b>⚡ רשימת המעקב</b>")
        for w in ev[:6]:
            lines.append(f"• <b>{e(w['t'])}</b> – {e(w['events'][0]['text'])} ➜ {e(w.get('action', ''))}")
    lines.append("<b>🔟 המניות של היום</b> (🌳 מתאימה גם לטווח ארוך · 🌱 מגמה ארוכה בבנייה · ⚡ מסחר קצר)")
    for p in rep["picks"]:
        ex = f" · ⚠️ דוח בעוד {max(0, p['earn'])} ימים" if p.get("earn") is not None and p["earn"] <= 10 else ""
        hzd = p.get("horizon") or {}
        hz = "🌳" if hzd.get("ok") else ("🌱" if hzd.get("label") == "מגמה ארוכה בבנייה" else "⚡")
        st = f" · סטופ {p['plan']['stop']:.2f}" if p.get("plan") else ""
        lines.append(f"{p['rank']}. {hz} <b>{e(p['t'].replace('.TA', ''))}</b> · {e(p['theme'])} · {round(p['score'])}{st}{ex}{tone(p['t'])}")
    if rep.get("israel"):
        lines.append("🇮🇱 " + " · ".join(e(p["t"].replace(".TA", "")) for p in rep["israel"]))
    Q = rep.get("quality_dips") or {}
    if Q.get("items"):
        lines.append(f"<b>💎 איכות בהנחה</b> (רווחיות, צומחות, קופה נזילה, ירדו 15%+ מהשיא)")
        for x in Q["items"][:6]:
            lines.append(f"• <b>{e(x['t'])}</b> {x['dd'] * 100:.0f}% מהשיא · צמיחה {x['rev_g'] * 100:.0f}% · רווחיות {x['margin'] * 100:.0f}%"
                         f"{' · 🔄 מתאוששת' if x['rebound'] else ''}{' · טכנולוגיה' if x['tech'] else ''}")
    xs = [x for x in rep.get("exits", []) if x.get("exit")]
    if xs:
        lines.append("<b>🚪 כלל יציאה (המלצות קודמות)</b>")
        for x in xs[:6]:
            lines.append(f"• <b>{e(x['t'])}</b> {x['ret']*100:+.1f}% מההמלצה ({e(x['since'][5:])}) – {e(' · '.join(x['why']))}")
    out_today = [x for x in rep.get("pick_track", []) if x["status"] == "out" and len(x["scores"]) >= 2 and x["scores"][-2][2]]
    if out_today:
        lines.append("<b>↩️ יצאו היום מהטופ</b>")
        for x in out_today[:5]:
            lines.append(f"• <b>{e(x['t'])}</b> – {e(x['reason'])}")
    stp = [x for x in rep.get("pick_track", []) if x.get("alert")]
    if stp:
        lines.append("⛔ התראות סטופ: " + " · ".join(f"<b>{e(x['t'])}</b> ({e(x['alert'][0])})" for x in stp[:6]))
    tr = [r for r in rep.get("track", []) if r.get("spy") is not None]
    if tr:
        ex = sum(r["ret"] - r["spy"] for r in tr) / len(tr) * 100
        beat = sum(r["ret"] > r["spy"] for r in tr) / len(tr) * 100
        lines.append(f"📏 מעקב: {len(tr)} המלצות · ממוצע מול S&P 500: {ex:+.1f}% · ניצחו את המדד: {beat:.0f}%")

    # ===== 3. דוח מחקר =====
    lines += ["", "<b>━━ 3 · דוח מחקר ━━</b>"]
    hl = []
    for t in list(by) + [p["t"] for p in rep["picks"]]:
        v = (news.get(t) or {}).get("verdict") or {}
        it = (news.get(t) or {}).get("items") or []
        if v.get("tone") in ("חיובי", "שלילי") and it and t not in [h[0] for h in hl]:
            hl.append((t, v, it[0]))
    for t, v, it in hl[:5]:
        lines.append(f"• <b>{e(t)}</b>: {e(it['title'][:90])} ({e(it['src'])}) – {e(v.get('conclusion', ''))}")
    if not hl:
        lines.append("אין פרסומים מהותיים היום.")
    links = [f'<a href="{e(url)}">הדוח המלא עם הרחבות ←</a>']
    if rep.get("research_url"):
        links.append(f'<a href="{e(rep["research_url"])}">חדר המחקר (אמירות טראמפ/פד/מאסק) ←</a>')
    lines += ["", "\n".join(links), "<i>כלי סינון אוטומטי, לא ייעוץ השקעות.</i>"]
    return "\n".join(lines)


def build_short(rep, url):
    """סופר-תקציר: השורות התחתונות + קישור לדוח המלא."""
    e = html.escape
    lines = [f"📈 <b>הדוח היומי</b> · סגירה {e(rep['asof'])}"]
    gen = rep.get("generated", "")
    try:
        age_h = (datetime.now(timezone.utc) - datetime.strptime(gen, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)).total_seconds() / 3600
    except ValueError:
        age_h = 0
    if age_h > 30:
        lines.append(f"⚠️ הדוח לא התעדכן מאז {e(gen)} – כנראה שהריצה הלילית נכשלה.")
    dot = {3: "🔴", 2: "🟠", 1: "🔵", 0: "🟢"}
    keep = ("מה לעשות היום", "יעד ההכנסה", "סטופ", "דוחות השבוע", "איכות בהנחה", "בקרה")
    ex_ = rep.get("exec") or []
    sel = [x for x in ex_ if x["k"].startswith(keep)] or ex_[:5]
    lines.append("")
    for x in sel:
        t = x["t"] if len(x["t"]) <= 160 else x["t"][:157] + "…"
        lines.append(f"{dot.get(x['lv'], '•')} <b>{e(x['k'])}:</b> {e(t)}")
    picks = rep.get("picks") or []
    if picks:
        lines.append("🏆 <b>טופ 5:</b> " + " · ".join(e(p["t"].replace(".TA", "")) for p in picks[:5]))
    lines += ["", f'👉 <b><a href="{e(url)}">לדוח המלא</a></b>']
    if rep.get("research_url"):
        lines.append(f'🔬 <a href="{e(rep["research_url"])}">חדר המחקר</a>')
    lines.append("<i>כלי סינון אוטומטי, לא ייעוץ השקעות.</i>")
    return "\n".join(lines)


def split_msg(msg, lim=3900):
    """טלגרם מגביל ל-4096 תווים – מפצלים בגבולות שורה כדי שהקישורים בסוף לא ייחתכו."""
    parts, cur = [], ""
    for ln in msg.split("\n"):
        ln = ln[:lim]
        if cur and len(cur) + len(ln) + 1 > lim:
            parts.append(cur)
            cur = ln
        else:
            cur = f"{cur}\n{ln}" if cur else ln
    if cur:
        parts.append(cur)
    return parts


def _file_chat():
    p = os.path.join(ROOT, "telegram_chat_id.txt")
    return open(p, encoding="utf-8").read().strip() if os.path.exists(p) else None


def tg_send(token, chat, msg):
    """שליחה לטלגרם. אם ה-CHAT_ID שגוי (למשל המספר של הבוט עצמו) – מאתר את הצ'אט שלך מהודעת Start ששלחת לבוט."""
    api = f"https://api.telegram.org/bot{token}/"
    bot_id = token.split(":")[0]
    post = lambda c: requests.post(api + "sendMessage", timeout=30, data={
        "chat_id": c, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": "true"})
    r = None
    for c in [x.strip() for x in (chat, _file_chat()) if x and x.strip() != bot_id]:
        r = post(c)
        if r.ok:
            return r
    try:
        ups = requests.get(api + "getUpdates", timeout=30).json().get("result", [])
    except Exception:  # noqa
        ups = []
    found = []
    for u in ups:
        ch = (u.get("message") or u.get("my_chat_member") or {}).get("chat") or {}
        if ch.get("type") == "private" and ch.get("id") not in found:
            found.append(ch.get("id"))
    for c in found:
        r = post(c)
        if r.ok:
            open(os.path.join(ROOT, "telegram_chat_id.txt"), "w").write(str(c))
            print("chat id saved to telegram_chat_id.txt")
            return r
    if r is None:
        print("no chat found – open your bot in Telegram and press Start")
        sys.exit(1)
    return r


def main():
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    rep = json.load(open(os.path.join(ROOT, "data", "latest.json"), encoding="utf-8"))
    url = os.environ.get("DASHBOARD_URL")
    if not url:
        repo = os.environ.get("GITHUB_REPOSITORY", "user/stock-radar")
        owner, name = repo.split("/")
        url = f"https://{owner.lower()}.github.io/{name}/"
    msg = build_short(rep, url) if os.environ.get("TG_FULL") != "1" else build(rep, url)
    if not token:
        print("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID not set – printing message only:\n")
        print(msg)
        return
    parts = split_msg(msg)
    for i, part in enumerate(parts):
        if len(parts) > 1:
            part = f"({i + 1}/{len(parts)})\n" + part
        r = tg_send(token, chat, part)
        print(i + 1, len(part), r.status_code, r.text[:200])
        if not r.ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
