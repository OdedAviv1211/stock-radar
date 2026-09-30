"""התראות "בדחיפה" לרשימת המעקב (watchlist.csv). רץ כל שעה בזמן המסחר (watch.yml).
שולח לטלגרם רק אירועים חדשים (לא חוזר על אותה התראה באותו יום). ללא Secrets – מדפיס בלבד.
אופציונלי: ACCOUNT_SIZE (משתנה ב-GitHub) – לחישוב כמות לפי סיכון 1% לעסקה."""
import html
import json
import os
import sys
from datetime import datetime, timezone

import requests

from screener import data, watch
from notify import tg_send

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "data", "watch_state.json")
MIN_URGENCY = int(os.environ.get("WATCH_MIN_URGENCY", "2"))


def run(hist=None, now=None):
    wl = watch.load_watchlist()
    if not wl:
        print("watchlist.csv ריק")
        return None, []
    tick = [r["ticker"] for r in wl]
    hist = hist or data.download_history(tick, period="2y")
    today = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
    if state.get("date") != today:
        state = {"date": today, "sent": {}}
    acct = float(os.environ["ACCOUNT_SIZE"]) if os.environ.get("ACCOUNT_SIZE") else None
    rows, alerts = [], []
    for r in wl:
        t = r["ticker"]
        ev = watch.evaluate(hist[t]) if t in hist else None
        if ev is None:
            rows.append({"t": t, "sector": r["sector"], "note": r.get("note", ""), "error": "אין נתונים"})
            continue
        ev["ticket"] = watch.order_ticket(t, ev, acct)
        rows.append({"t": t, "sector": r["sector"], "note": r.get("note", ""), **ev})
        sent = set(state["sent"].get(t, []))
        new = [e for e in ev["events"] if e["u"] >= MIN_URGENCY and e["key"] not in sent]
        if new:
            alerts.append((r, ev, new))
            state["sent"][t] = sorted(sent | {e["key"] for e in new})
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "rows": rows},
              open(os.path.join(ROOT, "data", "watch.json"), "w", encoding="utf-8"), ensure_ascii=False, default=float)
    return rows, alerts


def message(alerts):
    e = html.escape
    icon = {3: "🔴", 2: "🟠", 1: "⚪"}
    out = ["⚡ <b>התראת מעקב</b>"]
    for r, ev, new in sorted(alerts, key=lambda a: -max(x["u"] for x in a[2])):
        out += ["", f"{icon[max(x['u'] for x in new)]} <b>{e(r['ticker'])}</b> · {e(r['sector'])} · {ev['price']:.2f} ({ev['chg'] * 100:+.1f}%)"]
        out += [f"• {e(x['text'])}" for x in new]
        out.append(f"➜ <b>{e(ev['action'])}</b> · ממוצע 20: {ev['sma20']:.2f} ({ev['d20'] * 100:+.1f}%) · מיכה {ev['micha']}/6")
        tk = ev.get("ticket")
        if tk:
            q = f" · כמות {tk['qty']}" if tk["qty"] else ""
            out.append(f"📝 טיוטת פקודה: קנייה בלימיט {tk['limit']} · סטופ {tk['stop']}" + (f" · יעד {tk['target']}" if tk["target"] else "") + q)
    out += ["", "<i>הביצוע בידיים שלך. כלי סינון, לא ייעוץ השקעות.</i>"]
    return "\n".join(out)


def main():
    rows, alerts = run()
    if not alerts:
        print("אין אירועים חדשים")
        return
    msg = message(alerts)
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token:
        print(msg)
        return
    r = tg_send(token, chat, msg)
    print(r.status_code, r.text[:200])
    if not r.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
