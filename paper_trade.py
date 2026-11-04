"""תיק דמה מנוהל ב-Alpaca (Paper Trading) – גרסה 2, לפי "תוכנית ניהול התיק – גרסה 2" שאושרה ב-3.11.2026.

שני תיקים (חברה / אישי), בכל אחד שלושה חלקים: ארוך טווח · קצר טווח · מזומן.
python paper_trade.py            – ריצה לילית אחרי run.py: החלטות, פקודות לפתיחה הבאה, עדכון הדוח
python paper_trade.py --hourly   – כל שעה בזמן המסחר: מעקב ביצועים, סטופים, סטופ נגרר, מימוש חלקי, התראות

צריך Secrets: ALPACA_KEY_ID, ALPACA_SECRET_KEY (חשבון Paper בלבד). בלי מפתחות – לא עושה כלום.
מתג כיבוי: paper_enabled.txt (off = אף פקודה לא נשלחת).
"""
import csv
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from screener import config  # noqa: E402

BASE = "https://paper-api.alpaca.markets/v2"        # קבוע: רק חשבון דמה
DATA = "https://data.alpaca.markets/v2"
BOOK = os.path.join(ROOT, "data", "paper_book.json")
LOG = os.path.join(ROOT, "data", "paper_trades.csv")

ACCTS = {  # הקצאה לפי אופק (סעיף 3 בתוכנית)
    "C": {"key": "תיק ראשי", "name": "תיק החברה", "targets": {"long": .75, "short": .10, "cash": .15},
          "cap": config.ACCOUNTS["תיק ראשי"]["max_weight"], "deposit_ils": config.GOAL["monthly_contrib_ils"]},
    "P": {"key": "תיק אישי", "name": "תיק אישי", "targets": {"long": .85, "short": .10, "cash": .05},
          "cap": config.ACCOUNTS["תיק אישי"]["max_weight"], "deposit_ils": config.PERSONAL_PLAN["monthly_contrib_ils"]},
}
R = {  # כללים (סעיפים 5–6 בתוכנית)
    "band": 0.05,             # סטייה מותרת מיעד ההקצאה
    "earn_long": 7, "earn_short": 10,
    "short_slots": 4,         # עד 4 עסקאות קצרות בכל תיק
    "short_new_per_day": 2,
    "min_score": 85, "min_rs": 80,
    "breakout_gain": 0.03, "breakout_days": 3, "vol_mult": 1.5, "max_chase": 0.05,
    "stop": 0.08, "be_trigger": 0.08, "trail": 0.08, "target_R": 3,
    "time_days": 15, "time_min_gain": 0.05,
    "long_confirm_days": 5,
    "limit_pad": 0.01, "stale_days": 3, "max_orders": 15,
}


def log(m):
    print(f"[paper] {m}", flush=True)


def rnd(p):
    return round(p, 2) if p >= 1 else round(p, 4)


def now():
    return datetime.now(timezone.utc)


class Alpaca:
    def __init__(self, key, secret):
        self.h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        self.sent = 0

    def get(self, path, base=BASE, **params):
        r = requests.get(base + path, headers=self.h, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def order(self, body, force=False):
        if not force and self.sent >= R["max_orders"]:
            raise RuntimeError("daily order limit reached")
        r = requests.post(BASE + "/orders", headers=self.h, json=body, timeout=30)
        if not r.ok:
            raise RuntimeError(f"{r.status_code} {r.text[:200]}")
        self.sent += 1
        return r.json()

    def cancel(self, oid):
        return requests.delete(f"{BASE}/orders/{oid}", headers=self.h, timeout=30).ok

    def patch(self, oid, body):
        r = requests.patch(f"{BASE}/orders/{oid}", headers=self.h, json=body, timeout=30)
        return r.json() if r.ok else None

    def bars(self, syms, days=80):
        out = {}
        syms = sorted(set(syms))
        start = (now() - timedelta(days=int(days * 1.6))).strftime("%Y-%m-%dT00:00:00Z")
        for i in range(0, len(syms), 50):
            page = None
            while True:
                p = {"symbols": ",".join(syms[i:i + 50]), "timeframe": "1Day", "start": start, "limit": 10000,
                     "feed": "iex", "adjustment": "split"}
                if page:
                    p["page_token"] = page
                j = self.get("/stocks/bars", base=DATA, **p)
                for s, b in (j.get("bars") or {}).items():
                    out.setdefault(s, []).extend(b)
                page = j.get("next_page_token")
                if not page:
                    break
        return out


def cid(acct, kind, t):
    return f"rb_{acct}_{kind}_{t}_{now():%m%d%H%M%S%f}"[:120]


def parse_cid(c):
    p = (c or "").split("_")
    if len(p) < 5 or p[0] != "rb":
        return None
    return {"acct": p[1], "kind": p[2], "t": "_".join(p[3:-1])}


def logrow(rows, date):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "acct", "sleeve", "t", "side", "qty", "price", "why"])
        if new:
            w.writeheader()
        for d in rows:
            w.writerow({"date": date, **{k: d.get(k, "") for k in ("acct", "sleeve", "t", "side", "qty", "price", "why")}})


def enabled():
    p = os.path.join(ROOT, "paper_enabled.txt")
    return not os.path.exists(p) or open(p).read().strip().lower() not in ("off", "0", "false", "no")


# ---------- ספר הפנימי ----------
def load_book():
    if os.path.exists(BOOK):
        b = json.load(open(BOOK, encoding="utf-8"))
        if b.get("version") == 2:
            return b
    return None


def save_book(b):
    b["seen"] = b.get("seen", [])[-800:]
    json.dump(b, open(BOOK, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def apply_fills(api, book, events):
    """מעדכן את הספר לפי פקודות שבוצעו מאז הסנכרון האחרון."""
    after = book.get("last_sync") or (now() - timedelta(days=5)).isoformat()
    orders = api.get("/orders", status="closed", after=after, limit=500, direction="asc")
    seen = set(book.get("seen", []))
    for o in orders:
        q = float(o.get("filled_qty") or 0)
        info = parse_cid(o.get("client_order_id"))
        if not info or o["id"] in seen or q <= 0:
            continue
        seen.add(o["id"])
        book.setdefault("seen", []).append(o["id"])
        a = book["accounts"].get(info["acct"])
        if not a:
            continue
        px, t, k = float(o["filled_avg_price"]), info["t"], info["kind"]
        val = q * px
        if k == "M":
            book["mirror_pending"] = False
        if k in ("M", "L"):                       # קנייה לארוך טווח (M = העתקת התיק, ממומנת מהמאגר)
            h = a["long"].setdefault(t, {"qty": 0, "cost": 0})
            h["qty"] += q
            h["cost"] += val
            if k == "L":
                a["cash"] -= val
            events.append({"acct": info["acct"], "sleeve": "ארוך", "t": t, "side": "נקנתה", "qty": q, "price": px})
        elif k == "LS":                           # מכירה מהחלק הארוך
            h = a["long"].get(t)
            if h:
                avg = h["cost"] / h["qty"] if h["qty"] else 0
                h["qty"] -= q
                h["cost"] -= avg * q
                a["realized"] = a.get("realized", 0) + (px - avg) * q
                if h["qty"] <= 1e-6:
                    a["long"].pop(t, None)
            a["cash"] += val
            events.append({"acct": info["acct"], "sleeve": "ארוך", "t": t, "side": "נמכרה", "qty": q, "price": px})
        elif k == "S":                            # כניסה לעסקה קצרה
            s = a["short"].get(t)
            if s:
                tot = s["qty"] + q
                s["entry"] = (s["entry"] * s["qty"] + px * q) / tot
                s["qty"] = tot
            else:
                plan = book.get("plans", {}).get(t, {})
                stop0 = max(plan.get("stop") or 0, px * (1 - R["stop"]))
                stop0 = min(stop0, px * 0.995)
                a["short"][t] = {"qty": q, "entry": px, "stop": rnd(stop0), "stop0": rnd(stop0), "peak": px,
                                 "target": rnd(px + R["target_R"] * (px - stop0)), "half": False,
                                 "date": now().strftime("%Y-%m-%d"), "stop_id": None}
            a["short_cash"] -= val
            events.append({"acct": info["acct"], "sleeve": "קצר", "t": t, "side": "נקנתה", "qty": q, "price": px})
        elif k in ("SS", "SX"):                   # יציאה מעסקה קצרה (SX = סטופ)
            s = a["short"].get(t)
            if s:
                a["realized"] = a.get("realized", 0) + (px - s["entry"]) * q
                book.setdefault("closed", []).append({"acct": info["acct"], "t": t, "entry": s["entry"], "exit": px,
                                                      "qty": q, "ret": px / s["entry"] - 1, "date": now().strftime("%Y-%m-%d"),
                                                      "why": "סטופ" if k == "SX" else "יציאה לפי כלל"})
                s["qty"] -= q
                if s["qty"] <= 1e-6:
                    a["short"].pop(t, None)
            a["short_cash"] += val
            events.append({"acct": info["acct"], "sleeve": "קצר", "t": t, "side": "🛑 סטופ" if k == "SX" else "נמכרה",
                           "qty": q, "price": px})
    book["last_sync"] = now().isoformat()


def open_orders(api):
    out = []
    for o in api.get("/orders", status="open", limit=500):
        info = parse_cid(o.get("client_order_id"))
        if info:
            out.append({**info, "id": o["id"], "side": o["side"], "type": o["type"], "qty": float(o["qty"] or 0),
                        "created": o["created_at"], "stop_price": o.get("stop_price")})
    return out


# ---------- עזרי נתונים ----------
def sma(cl, n):
    return sum(cl[-n:]) / n if len(cl) >= n else None


def prices_from(rep):
    px = {}
    for grp in ("table", "portfolio", "picks", "picks_ext"):
        for r in rep.get(grp, []) or []:
            if r.get("t") and r.get("price"):
                px[r["t"]] = r["price"]
    for r in ((rep.get("quality_dips") or {}).get("items") or []):
        px[r["t"]] = r["price"]
    return px


def regime(rep):
    st = next((r.get("status", "") for r in rep.get("regime", []) if "SPY" in r.get("name", "")), "")
    if "יורדת" in st:
        return "down", st
    if "תיקון" in st:
        return "corr", st
    return "up", st


def acct_value(a, px):
    lv = sum(h["qty"] * px.get(t, h["cost"] / h["qty"] if h["qty"] else 0) for t, h in a["long"].items())
    sv = sum(s["qty"] * px.get(t, s["entry"]) for t, s in a["short"].items())
    return lv, sv, lv + sv + a["cash"] + a["short_cash"]


# ---------- אתחול: העתקת התיקים ----------
def init_book(api, rep, actions):
    px = prices_from(rep)
    spy = next((r.get("price") for r in rep.get("regime", []) if "SPY" in r.get("name", "")), None)
    # ניקוי פקודות ופוזיציות הניסיון של גרסה 1
    requests.delete(BASE + "/orders", headers=api.h, timeout=30)
    for p in api.get("/positions"):
        r = requests.delete(f"{BASE}/positions/{p['symbol']}", headers=api.h, timeout=30)
        if r.ok:
            actions.append({"acct": "-", "sleeve": "ניסיון", "t": p["symbol"], "side": "מכירה", "qty": float(p["qty"]),
                            "why": "סגירת פוזיציות הניסיון של גרסה 1"})
    book = {"version": 2, "start": rep["asof"], "start_spy": spy, "accounts": {}, "seen": [], "plans": {},
            "sell_watch": {}, "last_deposit": None, "closed": [], "last_sync": now().isoformat(),
            "just_init": True, "mirror_pending": True}
    for code, A in ACCTS.items():
        rows = [p for p in rep.get("portfolio", []) if p.get("notes") == A["key"] and p.get("shares")
                and not p["t"].endswith(".TA")]
        mirror = sum(p["shares"] * (px.get(p["t"]) or p.get("price") or 0) for p in rows)
        cash = float(config.CASH_USD.get(A["key"], 0))
        short_cash = round(A["targets"]["short"] * (mirror + cash), 2)
        start_val = mirror + cash + short_cash
        book["accounts"][code] = {"long": {}, "short": {}, "cash": cash, "short_cash": short_cash, "realized": 0,
                                  "contrib": start_val, "bench_shares": start_val / spy if spy else 0,
                                  "deposits": []}
        for p in rows:
            q = int(p["shares"])
            try:
                api.order({"symbol": p["t"], "qty": str(q), "side": "buy", "type": "market", "time_in_force": "day",
                           "client_order_id": cid(code, "M", p["t"])}, force=True)
                actions.append({"acct": code, "sleeve": "ארוך", "t": p["t"], "side": "קנייה", "qty": q,
                                "why": "העתקת התיק האמיתי"})
            except Exception as e:  # noqa
                actions.append({"acct": code, "sleeve": "ארוך", "t": p["t"], "side": "נכשל", "qty": q, "why": str(e)[:120]})
    return book


# ---------- ריצה לילית ----------
def nightly(api, rep, book, actions, events):
    px = prices_from(rep)
    reg, reg_txt = regime(rep)
    fx = rep.get("fx") or 3.7
    oo = open_orders(api)
    today = rep["asof"]

    # 1) ביטול פקודות קנייה ישנות
    for o in oo:
        if o["side"] == "buy" and o["type"] == "limit":
            age = (now() - datetime.fromisoformat(o["created"].replace("Z", "+00:00"))).days
            if age >= R["stale_days"] and api.cancel(o["id"]):
                actions.append({"acct": o["acct"], "sleeve": "", "t": o["t"], "side": "ביטול",
                                "why": f"לא בוצעה תוך {R['stale_days']} ימים"})
    oo = open_orders(api)
    pend = {(o["acct"], o["t"]) for o in oo if o["side"] == "buy"}

    pf = {(p["notes"], p["t"]): p for p in rep.get("portfolio", [])}
    left = {x["t"]: x for x in ((rep.get("quality_dips") or {}).get("left") or [])}
    stage = {r["t"]: r.get("stage") for r in rep.get("table", []) or []}
    earn = {r["t"]: r.get("earn") for g in ("table", "picks", "picks_ext", "portfolio") for r in rep.get(g, []) or []}

    # 0) השלמת העתקה: פקודות שנכשלו ביום ההעתקה (למשל בגלל פקודת מכירה פתוחה על אותה מניה) – עד 3 ניסיונות
    if not book.get("just_init") and book.get("mirror_tries", 0) < 3 and not book.get("mirror_done"):
        missing = 0
        for code, A in ACCTS.items():
            a = book["accounts"][code]
            for p in rep.get("portfolio", []):
                if p.get("notes") != A["key"] or not p.get("shares") or p["t"].endswith(".TA"):
                    continue
                have = a["long"].get(p["t"], {}).get("qty", 0) + sum(o["qty"] for o in oo if o["acct"] == code and o["t"] == p["t"] and o["kind"] == "M")
                diff = int(p["shares"]) - int(have)
                if diff > 0:
                    missing += 1
                    try:
                        api.order({"symbol": p["t"], "qty": str(diff), "side": "buy", "type": "market", "time_in_force": "day",
                                   "client_order_id": cid(code, "M", p["t"])}, force=True)
                        actions.append({"acct": code, "sleeve": "ארוך", "t": p["t"], "side": "קנייה", "qty": diff, "why": "השלמת העתקת התיק"})
                    except Exception as e:  # noqa
                        log(f"mirror retry {p['t']}: {e}")
        book["mirror_tries"] = book.get("mirror_tries", 0) + 1
        if missing == 0:
            book["mirror_done"] = True

    # 2) מכירות בחלק הארוך: העסק נשבר + המגמה שבורה, 5 ימי מסחר ברצף
    sw = book.setdefault("sell_watch", {})
    for code, a in book["accounts"].items():
        key = ACCTS[code]["key"]
        for t, h in list(a["long"].items()):
            row = pf.get((key, t))
            if row is not None:
                q = row.get("quality") or {}
                bad = row.get("action") == "לבחון צמצום" and (q.get("ok") is False or "הסטופ שהגדרת" in " ".join(row.get("signals") or []))
            else:
                bad = t in left and "לא עומדת" in left[t].get("why", "") and stage.get(t, 4) == 4
            k = f"{code}|{t}"
            if not bad:
                sw.pop(k, None)
                continue
            sw[k] = sw.get(k, 0) + 1
            if sw[k] >= R["long_confirm_days"] and not any(o["t"] == t and o["acct"] == code and o["side"] == "sell" for o in oo):
                q_ = int(h["qty"]) if float(h["qty"]).is_integer() else h["qty"]
                try:
                    api.order({"symbol": t, "qty": str(q_), "side": "sell", "type": "market", "time_in_force": "day",
                               "client_order_id": cid(code, "LS", t)})
                    actions.append({"acct": code, "sleeve": "ארוך", "t": t, "side": "מכירה", "qty": q_,
                                    "why": f"גם העסק וגם המגמה חלשים {sw[k]} ימי מסחר ברצף"})
                    sw.pop(k, None)
                except Exception as e:  # noqa
                    log(f"sell {t}: {e}")

    # 3) הפקדה חודשית (יום המסחר הראשון בחודש) + קניות לחלק הארוך
    book["regime"] = reg_txt
    month = today[:7]
    if book.get("just_init"):
        return                                   # ערב ההעתקה: הפקדה ועסקאות קצרות מהלילה הבא, אחרי שההעתקה בוצעה
    if book.get("last_deposit") != month:
        eq = float(api.get("/account")["equity"])
        used = sum(acct_value(a, px)[2] for a in book["accounts"].values())
        free = eq - used
        for code, a in book["accounts"].items():
            A = ACCTS[code]
            usd = round(A["deposit_ils"] / fx, 2)
            if free < usd:
                actions.append({"acct": code, "side": "הערה", "why": "המאגר הווירטואלי נגמר – צריך להגדיל (איפוס חשבון ב-Alpaca)"})
                continue
            free -= usd
            a["contrib"] += usd
            a["deposits"].append({"date": today, "usd": usd})
            spy = next((r.get("price") for r in rep.get("regime", []) if "SPY" in r.get("name", "")), None)
            if spy:
                a["bench_shares"] += usd / spy
            lv, sv, tot = acct_value(a, px)
            target_cash = A["targets"]["cash"] * tot
            to_cash = usd * 0.5 if a["cash"] < target_cash - R["band"] * tot else 0   # מזומן מתחת ליעד: חצי מההפקדה נשאר במזומן
            excess = max(0.0, a["cash"] - target_cash)
            a["cash"] += usd
            budget = min(a["cash"], usd - to_cash + excess)
            actions.append({"acct": code, "sleeve": "", "t": "", "side": "הפקדה", "qty": "",
                            "price": usd, "why": f"₪{A['deposit_ils']:,} · {'חצי למזומן (מתחת ליעד) · ' if to_cash else ''}תקציב קניות ${budget:,.0f}"})
            plan = next((p for p in rep.get("deposit_plan", []) if p.get("acct") == config.ACCOUNTS[A["key"]]["label"]), None)
            items = []
            for it in (plan or {}).get("items", []):
                t = it["t"]
                p = px.get(t)
                if not p or (code, t) in pend:
                    continue
                w = (a["long"].get(t, {}).get("qty", 0) * p) / tot if tot else 0
                if w >= A["cap"]:
                    continue
                if earn.get(t) is not None and 0 <= earn[t] <= R["earn_long"]:
                    continue
                if reg == "down" and "💎" not in it.get("why", "") and "באזור הוספה" not in it.get("why", ""):
                    continue
                items.append((t, p, it.get("why", "")))
            items = items[:3]
            for t, p, why in items:
                per = budget / len(items)
                q = math.floor(per / p)
                if q < 1:
                    continue
                try:
                    api.order({"symbol": t, "qty": str(q), "side": "buy", "type": "limit", "time_in_force": "gtc",
                               "limit_price": str(rnd(p * (1 + R["limit_pad"]))), "client_order_id": cid(code, "L", t)})
                    actions.append({"acct": code, "sleeve": "ארוך", "t": t, "side": "קנייה", "qty": q,
                                    "price": rnd(p * (1 + R["limit_pad"])), "why": "הפקדה: " + why})
                except Exception as e:  # noqa
                    log(f"buy {t}: {e}")
        book["last_deposit"] = month

    # 4) עסקאות קצרות: יציאות לפי סגירה (ממוצע 20, כלל זמן, דוח קרוב)
    syms = {t for a in book["accounts"].values() for t in a["short"]}
    cands = [p for p in rep.get("picks", []) or [] if not p["t"].endswith(".TA") and p.get("score", 0) >= R["min_score"]
             and p.get("stage") == 2 and (p.get("rs") or 0) >= R["min_rs"] and p.get("plan")
             and (p.get("earn") is None or p["earn"] > R["earn_short"])
             and ((p.get("si") or {}).get("vote", 0) >= 0)]          # שיטה 26: לא נכנסים כשהשורט עולה בחדות
    try:
        bars = api.bars(list(syms | {p["t"] for p in cands}), days=80) if (syms or cands) else {}
    except Exception as e:  # noqa
        log(f"bars failed: {e}")
        bars = {}
    for code, a in book["accounts"].items():
        for t, s in list(a["short"].items()):
            b = bars.get(t) or []
            cl = [x["c"] for x in b]
            why = None
            m20 = sma(cl, 20)
            if len(cl) >= 2 and m20 and cl[-1] < m20 and cl[-2] < sma(cl[:-1], 20):
                why = "שתי סגירות ברצף מתחת לממוצע 20"
            days = sum(1 for x in b if x["t"][:10] > s["date"])
            hi = max([x["h"] for x in b if x["t"][:10] >= s["date"]] or [s["entry"]])
            if not why and days >= R["time_days"] and hi < s["entry"] * (1 + R["time_min_gain"]):
                why = f"{days} ימי מסחר בלי רווח של {R['time_min_gain']:.0%}"
            e_ = earn.get(t)
            gain = (cl[-1] / s["entry"] - 1) if cl else 0
            qty = s["qty"]
            if not why and e_ is not None and 0 <= e_ <= 1:
                if gain < 0.10:
                    why = "דוח כספי מחר – רווח קטן מ-10%, יוצאים"
                elif not s["half"]:
                    why, qty = "דוח כספי מחר – מממשים חצי", math.floor(s["qty"] / 2)
                    s["half"] = True
            if why and qty >= 1:
                for o in oo:
                    if o["t"] == t and o["acct"] == code and o["side"] == "sell":
                        api.cancel(o["id"])
                s["stop_id"] = None
                try:
                    api.order({"symbol": t, "qty": str(int(qty)), "side": "sell", "type": "market", "time_in_force": "day",
                               "client_order_id": cid(code, "SS", t)})
                    actions.append({"acct": code, "sleeve": "קצר", "t": t, "side": "מכירה", "qty": int(qty), "why": why})
                except Exception as e:  # noqa
                    log(f"short exit {t}: {e}")

    # 5) עסקאות קצרות: כניסות חדשות
    if reg != "down":
        new = 0
        for code, a in book["accounts"].items():
            A = ACCTS[code]
            lv, sv, tot = acct_value(a, px)
            slots = R["short_slots"] if reg == "up" else R["short_slots"] // 2
            slot_usd = A["targets"]["short"] * tot / R["short_slots"] * (1 if reg == "up" else 0.5)
            open_n = len(a["short"]) + sum(1 for o in oo if o["acct"] == code and o["kind"] == "S")
            for p in cands:
                if new >= R["short_new_per_day"] or open_n >= slots:
                    break
                t = p["t"]
                if t in a["short"] or (code, t) in pend:
                    continue
                b = bars.get(t) or []
                if len(b) < 25:
                    continue
                cl, vol = [x["c"] for x in b], [x["v"] for x in b]
                last, pivot = cl[-1], p["plan"]["entry"]
                avgv = sum(vol[-51:-1]) / max(1, len(vol[-51:-1]))
                g3 = last / cl[-1 - R["breakout_days"]] - 1
                m20 = sma(cl, 20)
                brk = pivot <= last <= pivot * (1 + R["max_chase"]) and g3 >= R["breakout_gain"] and vol[-1] >= R["vol_mult"] * avgv
                pull = m20 and m20 <= last <= m20 * 1.02 and b[-1]["c"] > b[-1]["o"] and last <= pivot * (1 + R["max_chase"])
                if not (brk or pull):
                    continue
                q = math.floor(min(slot_usd, a["short_cash"]) / (last * (1 + R["limit_pad"])))
                if q < 1:
                    continue
                book.setdefault("plans", {})[t] = {"stop": p["plan"]["stop"], "pivot": pivot}
                try:
                    lim = rnd(last * (1 + R["limit_pad"]))
                    api.order({"symbol": t, "qty": str(q), "side": "buy", "type": "limit", "time_in_force": "gtc",
                               "limit_price": str(lim), "client_order_id": cid(code, "S", t)})
                    why = (f"פריצה: +{g3:.0%} ב-{R['breakout_days']} ימים, מחזור ×{vol[-1] / avgv:.1f}" if brk
                           else "חזרה לממוצע 20 במגמה עולה + יום היפוך")
                    actions.append({"acct": code, "sleeve": "קצר", "t": t, "side": "קנייה", "qty": q, "price": lim,
                                    "why": f"טופ {p.get('rank')} · ציון {round(p['score'])} · RS {p['rs']} · {why}"})
                    new += 1
                    open_n += 1
                except Exception as e:  # noqa
                    log(f"short buy {t}: {e}")
    book["regime"] = reg_txt


# ---------- מעקב (כל שעה + לילה): סטופים, סטופ נגרר, מימוש חלקי ----------
def monitor(api, book, actions, events):
    pos = {p["symbol"]: float(p["current_price"]) for p in api.get("/positions")}
    oo = open_orders(api)
    for code, a in book["accounts"].items():
        for t, s in list(a["short"].items()):
            price = pos.get(t)
            if price is None:
                continue
            s["peak"] = max(s["peak"], price)
            # מימוש חלקי ביעד: חצי, והסטופ של השאר עולה למחיר הכניסה
            if not s["half"] and price >= s["target"] and s["qty"] >= 2:
                half = math.floor(s["qty"] / 2)
                for o in oo:
                    if o["t"] == t and o["acct"] == code and o["kind"] == "SX":
                        api.cancel(o["id"])
                s["stop_id"] = None
                try:
                    api.order({"symbol": t, "qty": str(half), "side": "sell", "type": "market", "time_in_force": "day",
                               "client_order_id": cid(code, "SS", t)}, force=True)
                    s["half"] = True
                    s["stop"] = max(s["stop"], rnd(s["entry"]))
                    actions.append({"acct": code, "sleeve": "קצר", "t": t, "side": "מימוש חצי", "qty": half,
                                    "why": f"הגיעה ליעד {s['target']} (פי {R['target_R']} מהסיכון)"})
                except Exception as e:  # noqa
                    log(f"half {t}: {e}")
                continue
            new_stop = s["stop"]
            if price >= s["entry"] * (1 + R["be_trigger"]):
                new_stop = max(new_stop, s["entry"])
            if s["half"]:
                new_stop = max(new_stop, s["peak"] * (1 - R["trail"]), s["entry"])
            new_stop = rnd(new_stop)
            mine = [o for o in oo if o["t"] == t and o["acct"] == code and o["kind"] == "SX"]
            remaining = s["qty"]
            if not mine:
                try:
                    o = api.order({"symbol": t, "qty": str(int(remaining)), "side": "sell", "type": "stop",
                                   "time_in_force": "gtc", "stop_price": str(new_stop),
                                   "client_order_id": cid(code, "SX", t)}, force=True)
                    s["stop_id"] = o["id"]
                    s["stop"] = new_stop
                    events.append({"acct": code, "sleeve": "קצר", "t": t, "side": "סטופ הוצב", "price": new_stop})
                except Exception as e:  # noqa
                    log(f"stop {t}: {e}")
            elif new_stop > float(mine[0]["stop_price"] or 0) + 0.005:
                if api.patch(mine[0]["id"], {"stop_price": str(new_stop)}):
                    events.append({"acct": code, "sleeve": "קצר", "t": t, "side": "סטופ עלה", "price": new_stop})
                    s["stop"] = new_stop


# ---------- דוח ----------
def summary(api, rep, book, actions, events):
    pos = {p["symbol"]: float(p["current_price"]) for p in api.get("/positions")}
    px = {**prices_from(rep), **pos}
    spy = next((r.get("price") for r in rep.get("regime", []) if "SPY" in r.get("name", "")), None)
    eq = float(api.get("/account")["equity"])
    accts, used = [], 0
    for code, a in book["accounts"].items():
        A = ACCTS[code]
        lv, sv, tot = acct_value(a, px)
        used += tot
        bench = a["bench_shares"] * spy if spy else None
        longs = sorted([{"t": t, "qty": h["qty"], "price": px.get(t), "value": h["qty"] * (px.get(t) or 0),
                         "pl": (px.get(t) or 0) / (h["cost"] / h["qty"]) - 1 if h["qty"] and h["cost"] else None,
                         "w": h["qty"] * (px.get(t) or 0) / tot if tot else None,
                         "watch": book.get("sell_watch", {}).get(f"{code}|{t}")} for t, h in a["long"].items()],
                       key=lambda x: -x["value"])
        shorts = [{"t": t, "qty": s["qty"], "entry": s["entry"], "price": px.get(t), "stop": s["stop"], "target": s["target"],
                   "pl": (px.get(t) or s["entry"]) / s["entry"] - 1, "date": s["date"], "half": s["half"]} for t, s in a["short"].items()]
        pending = book.get("mirror_pending")
        accts.append({"code": code, "name": A["name"], "value": tot, "contrib": a["contrib"], "pending": pending,
                      "ret": None if pending else tot / a["contrib"] - 1,
                      "bench": bench, "bench_ret": bench / a["contrib"] - 1 if bench and not pending else None,
                      "alloc": {"long": lv / tot, "short": (sv + a["short_cash"]) / tot, "cash": a["cash"] / tot} if tot else {},
                      "targets": A["targets"], "cash": a["cash"], "short_cash": a["short_cash"], "realized": a.get("realized", 0),
                      "long": longs, "short": shorts, "deposits": a["deposits"][-3:]})
    closed = book.get("closed", [])
    wins = [c for c in closed if c["ret"] > 0]
    rep["paper"] = {"v": 2, "start": book["start"], "regime": book.get("regime"), "equity": eq, "reserve": eq - used,
                    "accounts": accts, "today": actions, "events": events[-20:], "rules": R,
                    "short_stats": {"n": len(closed), "win": len(wins) / len(closed) if closed else None,
                                    "avg_win": sum(c["ret"] for c in wins) / len(wins) if wins else None,
                                    "avg_loss": (sum(c["ret"] for c in closed if c["ret"] <= 0) / max(1, len(closed) - len(wins))) if closed else None,
                                    "last": closed[-5:]}}


def render(rep):
    json.dump(rep, open(os.path.join(ROOT, "data", "latest.json"), "w", encoding="utf-8"), ensure_ascii=False)
    tpl = open(os.path.join(ROOT, "screener", "template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/null", json.dumps(rep, ensure_ascii=False).replace("</", "<\\/"))
    open(os.path.join(ROOT, "docs", "index.html"), "w", encoding="utf-8").write(html)
    arch = os.path.join(ROOT, "docs", "archive", f"{rep['asof']}.html")
    if os.path.isdir(os.path.dirname(arch)):
        open(arch, "w", encoding="utf-8").write(html)


def telegram(events, actions):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    items = [e for e in events if e["side"] in ("נקנתה", "נמכרה", "🛑 סטופ")] + \
            [x for x in actions if x.get("side") == "מימוש חצי"]
    if not tok or not items:
        return
    try:
        import notify
        name = {"C": "חברה", "P": "אישי"}
        lines = ["🧪 <b>תיק דמה – עדכון</b>"] + [
            f"• {name.get(x.get('acct'), '')} · {x.get('sleeve', '')}: {x['side']} <b>{x['t']}</b>"
            + (f" ×{x['qty']:g}" if isinstance(x.get('qty'), (int, float)) else "")
            + (f" @ ${x['price']:.2f}" if isinstance(x.get('price'), (int, float)) else "") for x in items[:12]]
        notify.tg_send(tok, chat, "\n".join(lines))
    except Exception as e:  # noqa
        log(f"telegram: {e}")


def main():
    hourly = "--hourly" in sys.argv
    key, sec = os.environ.get("ALPACA_KEY_ID"), os.environ.get("ALPACA_SECRET_KEY")
    if not key or not sec:
        log("ALPACA keys not set – skipping")
        return
    if not enabled():
        log("paper_enabled.txt = off – no orders")
        return
    api = Alpaca(key, sec)
    rep = json.load(open(os.path.join(ROOT, "data", "latest.json"), encoding="utf-8"))
    book = load_book()
    actions, events = [], []
    if book is None:
        if hourly:
            log("book not initialized yet – waiting for nightly run")
            return
        book = init_book(api, rep, actions)
        save_book(book)                          # נשמר מיד – כדי שלא תהיה העתקה כפולה
    else:
        book.pop("just_init", None)
        apply_fills(api, book, events)
    if not hourly:
        nightly(api, rep, book, actions, events)
    monitor(api, book, actions, events)
    save_book(book)
    logrow(actions + [dict(e, why=e.get("why", "ביצוע")) for e in events], rep["asof"] if not hourly else now().strftime("%Y-%m-%d %H:%M"))
    if hourly:
        telegram(events, actions)
    else:
        summary(api, rep, book, actions, events)
        render(rep)
    log(f"done · actions {len(actions)} · events {len(events)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa – תיק הדמה לא יפיל את הדוח היומי
        log(f"paper trading failed: {e}")
        sys.exit(0)
