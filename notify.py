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
    lines = [f"📈 <b>רדאר מניות יומי</b> · {e(rep['asof'])}"]
    gen = rep.get("generated", "")
    try:
        age_h = (datetime.now(timezone.utc) - datetime.strptime(gen, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)).total_seconds() / 3600
    except ValueError:
        age_h = 0
    if age_h > 30:
        lines.append(f"⚠️ הדוח לא התעדכן מאז {e(gen)} – כנראה שהריצה הלילית נכשלה (לבדוק בלשונית Actions).")
    reg = " · ".join(f"{e(r['name'].split(' (')[0])}: {e(r['status'])}" for r in rep["regime"])
    lines += ["", f"<b>מצב השוק</b>\n{reg}"]
    if rep["regime"][0].get("level", 0) < 0:
        lines.append("⚠️ S&amp;P 500 מתחת לממוצע 150 – להקטין סיכון.")

    pf = [p for p in rep.get("portfolio", []) if p.get("level", 0) >= 2]
    if pf:
        lines += ["", "<b>🔔 התיק שלך</b>"]
        for p in pf:
            icon = "🔴" if p["level"] >= 3 else "🟠"
            lines.append(f"{icon} <b>{e(p['t'])}</b> {pct(p.get('ret'))} – {e(p['signals'][0])}")

    lines += ["", "<b>10 המניות של היום</b>"]
    for p in rep["picks"]:
        extra = []
        if p.get("pats"):
            extra.append(p["pats"][0]["name"])
        if p.get("earn") is not None and p["earn"] <= 10:
            extra.append(f"⚠️ דוח בעוד {max(0, p['earn'])} ימים")
        ex = f" · {e(' · '.join(extra))}" if extra else ""
        lines.append(f"{p['rank']}. <b>{e(p['t'].replace('.TA', ''))}</b> · {e(p['theme'])} · ציון {round(p['score'])} · RS {p['rs']}{ex}")
    if rep.get("israel"):
        lines += ["", "<b>🇮🇱 ת\"א:</b> " + " · ".join(f"{e(p['t'].replace('.TA', ''))} ({round(p['score'])})" for p in rep["israel"])]
    hot = [t for t in rep.get("industries", []) if t["mk"] == "US"][:3]
    if hot:
        lines += ["", "<b>ענפים מובילים:</b> " + " · ".join(e(g["name"]) for g in hot)]
    lines += ["", f'<a href="{e(url)}">לדשבורד המלא ←</a>', "<i>כלי סינון אוטומטי, לא ייעוץ השקעות.</i>"]
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
