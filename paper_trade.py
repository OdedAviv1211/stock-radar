"""תיק דמה ב-Alpaca (Paper Trading): מבצע את המלצות הרדאר בכסף וירטואלי ומודד מול S&P 500.
רץ אחרי run.py. צריך שני Secrets במאגר: ALPACA_KEY_ID ו-ALPACA_SECRET_KEY (מחשבון ה-Paper בלבד).
בלי מפתחות – לא עושה כלום. עובד רק מול paper-api (כסף וירטואלי), אף פעם לא מול חשבון אמיתי."""
import csv
import json
import math
import os
import sys
from datetime import datetime, timezone

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = "https://paper-api.alpaca.markets/v2"   # קבוע: רק חשבון דמה
POS_PCT = 0.05          # כל קנייה = 5% משווי תיק הדמה
MAX_POS = 20            # עד 20 פוזיציות
MAX_NEW = 3             # עד 3 קניות חדשות ביום
QUALITY_STOP = 0.15     # מניות איכות לטווח ארוך: סטופ רחב 15% מתחת למחיר הכניסה
STALE_DAYS = 3          # פקודת קנייה שלא בוצעה תוך 3 ימים – מבוטלת


def log(m):
    print(f"[paper] {m}", flush=True)


def rnd(p):
    return round(p, 2) if p >= 1 else round(p, 4)


class Alpaca:
    def __init__(self, key, secret):
        self.h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

    def get(self, path, **params):
        r = requests.get(BASE + path, headers=self.h, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def post(self, path, body):
        r = requests.post(BASE + path, headers=self.h, json=body, timeout=30)
        if not r.ok:
            raise RuntimeError(f"{r.status_code} {r.text[:200]}")
        return r.json()

    def delete(self, path):
        r = requests.delete(BASE + path, headers=self.h, timeout=30)
        return r.ok


def prices(rep):
    px = {}
    for r in rep.get("table", []) or []:
        if r.get("t") and r.get("price"):
            px[r["t"]] = r["price"]
    for grp in ("portfolio", "picks", "picks_ext"):
        for r in rep.get(grp, []) or []:
            if r.get("t") and r.get("price"):
                px[r["t"]] = r["price"]
    for r in ((rep.get("quality_dips") or {}).get("items") or []):
        px[r["t"]] = r["price"]
    return px


def candidates(rep, px):
    """סדר עדיפויות: איכות בהנחה שמתאוששת → תוכנית ההפקדה → 🌳 מהטופ. מחזיר (טיקר, סטופ, סיבה)."""
    out, seen = [], set()

    def add(t, stop, why):
        if t and t not in seen and not t.endswith(".TA") and px.get(t):
            seen.add(t)
            out.append((t, stop, why))
    for x in ((rep.get("quality_dips") or {}).get("items") or []):
        if x.get("verdict", "").endswith("מועמדת לקנייה הדרגתית"):
            add(x["t"], x["price"] * (1 - QUALITY_STOP), f"💎 איכות בהנחה {x.get('grade', '')}{x.get('score', '')}")
    for plan in rep.get("deposit_plan", []) or []:
        for it in plan.get("items", []):
            add(it["t"], px.get(it["t"], 0) * (1 - QUALITY_STOP), "תוכנית ההפקדה: " + it.get("why", ""))
    for p in rep.get("picks", []) or []:
        if (p.get("horizon") or {}).get("ok") and p.get("plan"):
            add(p["t"], p["plan"]["stop"], f"🌳 טופ 10 (מקום {p.get('rank')})")
    return out


def sells(rep, held):
    """יציאות: מניה שהרדאר סימן לה יציאה, או שיצאה מ'איכות בהנחה' כי כבר לא איכותית."""
    out = {}
    for x in rep.get("exits", []) or []:
        if x.get("exit") and x["t"] in held:
            out[x["t"]] = "יציאה לפי הרדאר: " + " · ".join(x.get("why", []))
    for x in ((rep.get("quality_dips") or {}).get("left") or []):
        if x["t"] in held and "לא עומדת" in x.get("why", ""):
            out[x["t"]] = "כבר לא עומדת בתנאי האיכות"
    return out


def render(rep):
    """מעדכן את הדוח (latest.json + index.html) עם נתוני תיק הדמה."""
    json.dump(rep, open(os.path.join(ROOT, "data", "latest.json"), "w", encoding="utf-8"), ensure_ascii=False)
    tpl = open(os.path.join(ROOT, "screener", "template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/null", json.dumps(rep, ensure_ascii=False).replace("</", "<\\/"))
    open(os.path.join(ROOT, "docs", "index.html"), "w", encoding="utf-8").write(html)
    arch = os.path.join(ROOT, "docs", "archive", f"{rep['asof']}.html")
    if os.path.exists(os.path.dirname(arch)):
        open(arch, "w", encoding="utf-8").write(html)


def main():
    key, sec = os.environ.get("ALPACA_KEY_ID"), os.environ.get("ALPACA_SECRET_KEY")
    if not key or not sec:
        log("ALPACA_KEY_ID / ALPACA_SECRET_KEY not set – skipping paper trading")
        return
    rep = json.load(open(os.path.join(ROOT, "data", "latest.json"), encoding="utf-8"))
    api = Alpaca(key, sec)
    acct = api.get("/account")
    eq, cash = float(acct["equity"]), float(acct["cash"])
    pos = {p["symbol"]: p for p in api.get("/positions")}
    orders = api.get("/orders", status="open", nested="true", limit=500)
    now = datetime.now(timezone.utc)
    done = []

    # 1) ביטול פקודות קנייה ישנות שלא בוצעו
    pending = set()
    for o in orders:
        if o["side"] == "buy":
            age = (now - datetime.fromisoformat(o["created_at"].replace("Z", "+00:00"))).days
            if age >= STALE_DAYS:
                api.delete(f"/orders/{o['id']}")
                done.append({"t": o["symbol"], "side": "cancel", "why": f"לא בוצעה תוך {STALE_DAYS} ימים"})
            else:
                pending.add(o["symbol"])

    # 2) מכירות
    for t, why in sells(rep, set(pos)).items():
        for o in orders:
            if o["symbol"] == t:
                api.delete(f"/orders/{o['id']}")
        if api.delete(f"/positions/{t}"):
            done.append({"t": t, "side": "sell", "qty": float(pos[t]["qty"]), "why": why})
            pos.pop(t, None)

    # 3) קניות
    px = prices(rep)
    n_new = 0
    for t, stop, why in candidates(rep, px):
        if n_new >= MAX_NEW or len(pos) + len(pending) >= MAX_POS:
            break
        if t in pos or t in pending:
            continue
        price = px[t]
        budget = min(eq * POS_PCT, cash * 0.95)
        qty = math.floor(budget / price)
        if qty < 1 or not stop or stop >= price:
            continue
        lim = rnd(price * 1.01)
        body = {"symbol": t, "qty": str(qty), "side": "buy", "type": "limit", "time_in_force": "gtc",
                "limit_price": str(lim), "order_class": "oto", "stop_loss": {"stop_price": str(rnd(stop))}}
        try:
            api.post("/orders", body)
        except Exception as e:  # noqa
            log(f"order {t} failed: {e}")
            continue
        cash -= qty * lim
        n_new += 1
        pending.add(t)
        done.append({"t": t, "side": "buy", "qty": qty, "limit": lim, "stop": rnd(stop), "why": why})

    # 4) יומן + מצב מול S&P 500
    lp = os.path.join(ROOT, "data", "paper_log.csv")
    new = not os.path.exists(lp)
    with open(lp, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "t", "side", "qty", "limit", "stop", "why"])
        if new:
            w.writeheader()
        for d in done:
            w.writerow({"date": rep["asof"], **{k: d.get(k, "") for k in ("t", "side", "qty", "limit", "stop", "why")}})
    sp = os.path.join(ROOT, "data", "paper_state.json")
    spy = next((r.get("price") for r in rep.get("regime", []) if "SPY" in r.get("name", "")), None)
    st = json.load(open(sp)) if os.path.exists(sp) else {"start_date": rep["asof"], "start_equity": eq, "start_spy": spy}
    json.dump(st, open(sp, "w"))
    acct = api.get("/account")
    eq = float(acct["equity"])
    plist = [{"t": p["symbol"], "qty": float(p["qty"]), "entry": float(p["avg_entry_price"]), "price": float(p["current_price"]),
              "value": float(p["market_value"]), "pl": float(p["unrealized_plpc"])} for p in api.get("/positions")]
    rep["paper"] = {"start": st["start_date"], "equity": eq, "cash": float(acct["cash"]),
                    "ret": eq / st["start_equity"] - 1 if st.get("start_equity") else None,
                    "spy_ret": spy / st["start_spy"] - 1 if spy and st.get("start_spy") else None,
                    "positions": sorted(plist, key=lambda x: -x["value"]), "today": done,
                    "pending": sorted(pending), "rules": {"pos_pct": POS_PCT, "max_pos": MAX_POS, "max_new": MAX_NEW,
                                                          "quality_stop": QUALITY_STOP}}
    render(rep)
    log(f"equity ${eq:,.0f} · positions {len(plist)} · today {len(done)} actions")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa – תיק הדמה לא יפיל את הדוח היומי
        log(f"paper trading failed: {e}")
        sys.exit(0)
