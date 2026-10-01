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
    lines.append("<b>🔟 המניות של היום</b>")
    for p in rep["picks"]:
        ex = f" · ⚠️ דוח בעוד {max(0, p['earn'])} ימים" if p.get("earn") is not None and p["earn"] <= 10 else ""
        lines.append(f"{p['rank']}. <b>{e(p['t'].replace('.TA', ''))}</b> · {e(p['theme'])} · {round(p['score'])}{ex}{tone(p['t'])}")
    if rep.get("israel"):
        lines.append("🇮🇱 " + " · ".join(e(p["t"].replace(".TA", "")) for p in rep["israel"]))

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


def _file_chat():
    p = os.path.join(ROOT, "telegram_chat_id.txt")
    return open(p, encoding="utf-8").read().strip() if os.path.exists(p) else None


def tg_send(token, chat, msg):
    """שליחה לטלגרם. אם ה-CHAT_ID שגוי (למשל המספר של הבוט עצמו) – מאתר את הצ'אט שלך מהודעת Start ששלחת לבוט."""
    api = f"https://api.telegram.org/bot{token}/"
    bot_id = token.split(":")[0]
    post = lambda c: requests.post(api + "sendMessage", timeout=30, data={
        "chat_id": c, "text": msg[:4000], "parse_mode": "HTML", "disable_web_page_preview": "true"})
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
    msg = build(rep, url)
    if not token:
        print("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID not set – printing message only:\n")
        print(msg)
        return
    r = tg_send(token, chat, msg)
    print(r.status_code, r.text[:300])
    if not r.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
