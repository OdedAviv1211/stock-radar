"""הצינור היומי: יקום ← נתונים ← אינדיקטורים ← דמיון למנצחות ← ניקוד ← בחירת 10 ← דשבורד."""
import csv
import json
import math
import os
from datetime import datetime

import numpy as np

from . import watch, analogs, config, data, micha, patterns, scoring, themes
from .indicators import compute

ROOT = data.ROOT
log = data.log


def cap_class(mcap):
    if not mcap:
        return "לא ידוע"
    for th, name in config.CAP_CLASSES:
        if mcap >= th:
            return name
    return "קטנה"


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if (math.isnan(o) or math.isinf(o)) else round(float(o), 5)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def regime(df, name):
    f = compute(df) if df is not None else None
    if not f:
        return {"name": name, "status": "לא זמין", "level": 0}
    if f["price"] > f["sma150"] and f["sma150_slope"] > 0 and f["price"] > f["sma50"]:
        st, lv = "מגמה עולה", 2
    elif f["price"] > f["sma150"]:
        st, lv = "עולה בתיקון", 1
    elif f["sma150_slope"] > 0:
        st, lv = "תיקון – מתחת לממוצע 150", -1
    else:
        st, lv = "מגמה יורדת", -2
    return {"name": name, "status": st, "level": lv, "price": f["price"], "r1d": f["r1d"], "r21": f["r21"],
            "ext_sma150": f["ext_sma150"], "dist_hi": f["dist_hi"]}


def load_weights():
    path = os.path.join(ROOT, "data", "weights.json")
    w = dict(config.WEIGHTS)
    src = "ברירת מחדל"
    if config.USE_CALIBRATED_WEIGHTS and os.path.exists(path):
        try:
            j = json.load(open(path, encoding="utf-8"))
            if j.get("adopted") and set(j["weights"]) == set(w):
                w, src = j["weights"], f"מכויל בבדיקה לאחור ({j.get('date', '')})"
        except Exception as e:  # noqa
            log(f"weights.json ignored: {e}")
    return w, src


def watch_rows(wl, hist):
    out = []
    for r in wl:
        try:
            ev = watch.evaluate(hist[r["ticker"]]) if r["ticker"] in hist else None
        except Exception:  # noqa
            ev = None
        out.append({"t": r["ticker"], "sector": r["sector"], "note": r.get("note", ""), **(ev or {"error": "אין נתונים"})})
    return out


def run(today=None):
    t0 = datetime.utcnow()
    now_ts = datetime.utcnow().timestamp()
    scoring.W, weights_src = load_weights()
    us, tase = data.us_universe(), data.tase_universe()
    meta = {x["ticker"]: x for x in us + tase}
    portfolio = data.load_portfolio()
    for pz in portfolio:
        if pz["ticker"] not in meta:
            meta[pz["ticker"]] = {"ticker": pz["ticker"], "name": pz["ticker"], "mcap": None, "sector": "",
                                  "industry": "", "market": "TASE" if pz["ticker"].endswith(".TA") else "US",
                                  "pf_only": True}
    benches = [config.BENCH_US, config.BENCH_US2, config.BENCH_TASE, config.FX_ILS]
    wl = watch.load_watchlist()
    hist = data.download_history(list(dict.fromkeys(list(meta) + [r["ticker"] for r in wl])) + benches)
    spy = hist.get(config.BENCH_US)
    if spy is None:
        raise RuntimeError("SPY history missing – aborting")
    ta = hist.get(config.BENCH_TASE)
    fx = float(hist[config.FX_ILS]["Close"].iloc[-1]) if config.FX_ILS in hist else 3.7
    asof = str(spy.index[-1].date())
    log(f"history for {len(hist)} tickers, as of {asof}, USD/ILS {fx:.3f}")

    # ---- אינדיקטורים ----
    feats = {}
    for t, df in hist.items():
        if t in benches or t not in meta:
            continue
        b = (ta["Close"] if ta is not None else None) if meta[t]["market"] == "TASE" else spy["Close"]
        try:
            f = compute(df, b)
        except Exception as e:  # noqa
            log(f"compute {t}: {e}")
            f = None
        if f:
            if meta[t]["market"] == "TASE":  # מחירי ת"א ביאהו באגורות
                f["dollar_vol"] = f["dollar_vol"] / 100 / fx
            feats[t] = f
    log(f"features: {len(feats)}")

    # שווי שוק לת"א
    tase_t = [t for t in feats if meta[t]["market"] == "TASE"]
    for t, (mc, cur) in data.tase_market_caps(tase_t).items():
        if mc:
            ils = mc / 100 if (cur or "ILA") == "ILA" else mc
            meta[t]["mcap"] = ils / fx
    # גיבוי כשאין שווי שוק: הערכה לפי מחזור (לצורכי גודל במפת חום בלבד)
    for t in feats:
        meta[t]["mcap_est"] = meta[t]["mcap"] or feats[t]["dollar_vol"] * 150

    us_t = [t for t in feats if meta[t]["market"] == "US"]
    rs = scoring.rs_ratings(feats, [us_t, tase_t])

    # ---- דירוג ענפים (IBD Industry Groups): חציון החוזק היחסי של המניות בענף ----
    def gkey(t):
        m = meta[t]
        return (m["market"], m.get("industry") or m.get("sector") or "אחר")
    gvals = {}
    for t, f in feats.items():
        if not np.isnan(f["rs_raw"]):
            gvals.setdefault(gkey(t), []).append(f["rs_raw"])
    groups = {}
    for mk in ("US", "TASE"):
        gs = [(k, float(np.median(v)), len(v)) for k, v in gvals.items() if k[0] == mk and len(v) >= 3]
        gs.sort(key=lambda x: -x[1])
        for i, (k, med, n) in enumerate(gs):
            groups[k] = {"name": k[1], "mk": mk, "rank": i + 1, "of": len(gs), "n": n, "med_rs": med,
                         "rank_pct": 100 * (1 - i / max(1, len(gs) - 1)) if len(gs) > 1 else 50}

    # ---- דמיון למנצחות היסטוריות ----
    win_t = sorted({w[0] for w in analogs.WINNERS})
    whist = data.download_history(win_t + [config.BENCH_US], start="2014-01-01")
    lib = analogs.build_library(whist, whist.get(config.BENCH_US, spy)["Close"])
    log(f"analog library: {len(lib)} fingerprints")
    sims = analogs.score_similarity(feats, lib)

    pf_set = {pz["ticker"] for pz in portfolio}
    # ---- ניקוד שלב א' (טכני) ----
    rows = {}
    for t, f in feats.items():
        r = rs.get(t, 50)
        tr, ttc = scoring.trend_score(f, r)
        sim, an = sims.get(t, (0.0, None))
        mk = meta[t]["market"]
        min_dv = config.US_MIN_DOLLAR_VOL if mk == "US" else config.TASE_MIN_DOLLAR_VOL
        eligible = f["stage"] == 2 and f["dollar_vol"] >= min_dv and f["sma150_slope"] > 0 and \
            (mk != "US" or f["price"] >= config.US_MIN_PRICE)
        pats = patterns.detect(hist[t]) if eligible else []
        mch = micha.analyze(hist[t], pats) if (eligible or t in pf_set) else None
        grp = groups.get(gkey(t))
        parts = {"trend": tr, "rs": float(r), "analog": sim, "fund": 50.0,
                 "group": grp["rank_pct"] if grp else 50.0, "accum": scoring.accum_score(f),
                 "setup": min(100.0, scoring.setup_score(f) + scoring.pattern_bonus(pats) + 2.0 * (mch["score"] if mch else 0))}
        rows[t] = {"t": t, "f": f, "rs": r, "tt": ttc, "parts": parts, "analog": an, "sim": sim, "pats": pats, "micha": mch,
                   "group": grp, "score": scoring.composite(parts), "eligible": eligible, "info": None,
                   "fund_ok": False, "earn": None}

    elig = sorted([x for x in rows.values() if x["eligible"]], key=lambda x: -x["score"])
    cand = [x["t"] for x in elig if meta[x["t"]]["market"] == "US"][:config.N_FUNDAMENTALS] + \
           [x["t"] for x in elig if meta[x["t"]]["market"] == "TASE"][:25]
    log(f"eligible {len(elig)}, fundamentals for {len(cand)}")
    pf_t = [pz["ticker"] for pz in portfolio if pz["ticker"] in feats]
    infos = data.fundamentals(list(dict.fromkeys(cand + pf_t)))

    # ---- ניקוד שלב ב' (עם פונדמנטלי) + סיווג ----
    for t, x in rows.items():
        info = infos.get(t)
        m = meta[t]
        if info:
            x["info"] = info
            x["parts"]["fund"], x["fund_ok"] = scoring.fund_score(info)
            x["score"] = scoring.composite(x["parts"])
            x["earn"] = scoring.days_to_earnings(info, now_ts)
            if x["earn"] is not None and x["earn"] <= config.EARNINGS_PENALTY_DAYS:
                x["score"] -= config.EARNINGS_PENALTY
            if not m["sector"] and info.get("sector"):
                m["sector"], m["industry"] = info.get("sector"), info.get("industry") or ""
            if not m["mcap"] and info.get("marketCap") and m["market"] == "US":
                m["mcap"] = info["marketCap"]
            if info.get("longName"):
                m["name"] = info["longName"]
        dy = None
        if info:
            dy = info.get("trailingAnnualDividendYield")
            if dy is None and info.get("dividendYield") is not None:
                dy = info["dividendYield"] / 100 if info["dividendYield"] > 1 else info["dividendYield"]
        x["div"] = dy
        x["theme"], x["sub"], x["tags"] = themes.classify(t, m["sector"], m["industry"], dy)
        x["cap"] = cap_class(m["mcap"])

    cand_set = set(cand)
    ranked = sorted([x for x in rows.values() if x["t"] in cand_set and x["eligible"]], key=lambda x: -x["score"])

    # ---- בחירת 10 עם פיזור לפי קטגוריה ----
    picks, per_theme = [], {}
    for x in ranked:
        if meta[x["t"]]["market"] != "US" and len([p for p in picks if meta[p["t"]]["market"] != "US"]) >= 2:
            continue
        if per_theme.get(x["theme"], 0) >= config.MAX_PER_THEME:
            continue
        picks.append(x)
        per_theme[x["theme"]] = per_theme.get(x["theme"], 0) + 1
        if len(picks) == config.TOP_N:
            break
    israel = [x for x in ranked if meta[x["t"]]["market"] == "TASE"][:config.ISRAEL_TOP_N]
    by_cap = {c: [x for x in ranked if x["cap"] == c][:5] for c in ["מגה", "גדולה", "בינונית", "קטנה"]}

    def card(x, rank=None, series=False):
        t, f, m = x["t"], x["f"], meta[x["t"]]
        good, warn = scoring.reasons(f, x["rs"], x["tt"], x["info"], x["analog"], x["sim"], x["pats"],
                                     x["group"], x["earn"])
        mc = x.get("micha")
        if mc:
            okn = [ch["name"] for ch in mc["checks"] if ch["ok"]]
            if mc["score"] >= 3:
                good.append(f"שיטות מיכה סטוקס: {mc['score']}/6 מתקיימות ({', '.join(okn)})")
            if mc.get("hs"):
                warn.append(f"תבנית ראש וכתפיים – שבירת קו הצוואר ({mc['hs']['neck']:.2f}), סימן היפוך")
            tl = mc["checks"][3]
            if "שברה" in tl["note"]:
                warn.append("המחיר שבר את קו המגמה העולה")
        if "השקעת NVIDIA" in x["tags"]:
            warn.append("NVIDIA מחזיקה/השקיעה בחברה – בבדיקה, האפקט ממומש בעיקר ביום ההכרזה ולא מבטיח המשך; "
                        "כשהחברה גם לקוחה של NVIDIA יש סיכון מעגליות")
        o = {"rank": rank, "t": t, "name": m["name"], "mk": m["market"], "theme": x["theme"], "sub": x["sub"],
             "tags": x["tags"], "cap": x["cap"], "mcap": m["mcap"], "score": x["score"], "parts": x["parts"],
             "rs": x["rs"], "tt": x["tt"], "stage": f["stage"], "price": f["price"], "r1d": f["r1d"],
             "r21": f["r21"], "r63": f["r63"], "r252": f["r252"], "dist_hi": f["dist_hi"],
             "ext150": f["ext_sma150"], "good": good, "warn": warn, "plan": scoring.trade_plan(f, mc),
             "micha": ({"score": mc["score"], "checks": [{"n": ch["name"], "ok": ch["ok"], "note": ch["note"]} for ch in mc["checks"]]}
                       if mc else None),
             "cur": "אג'" if m["market"] == "TASE" else "$", "div": x.get("div"), "earn": x["earn"],
             "pats": [{"name": p["name"], "pivot": p["pivot"], "dist": p["dist"]} for p in x["pats"]],
             "grp": ({"name": x["group"]["name"], "rank": x["group"]["rank"], "of": x["group"]["of"]}
                     if x["group"] else None),
             "analog": ({"label": x["analog"]["label"], "t": x["analog"]["ticker"], "date": x["analog"]["date"],
                         "fwd6": x["analog"]["fwd6"], "fwd12": x["analog"]["fwd12"], "sim": x["sim"]}
                        if x["analog"] else None)}
        if x["info"]:
            i = x["info"]
            o["fund"] = {"rev_g": i.get("revenueGrowth"), "eps_g": i.get("earningsQuarterlyGrowth"),
                         "gm": i.get("grossMargins"), "roe": i.get("returnOnEquity"), "fpe": i.get("forwardPE"),
                         "peg": i.get("trailingPegRatio"), "inst": i.get("heldPercentInstitutions"),
                         "target": i.get("targetMeanPrice"), "rec": i.get("recommendationMean")}
        if series:
            s = compute(hist[t], with_series=True)["series"]
            o["series"] = s
        return o

    # ---- מפת חום ----
    heat = []
    for mk in ("US", "TASE"):
        by_sec = {}
        for t, f in feats.items():
            m = meta[t]
            if m["market"] != mk or m.get("pf_only"):
                continue
            by_sec.setdefault(themes.sector_he(m["sector"]), []).append(t)
        for sec, ts in by_sec.items():
            ts = sorted(ts, key=lambda t: -(meta[t]["mcap"] or meta[t]["mcap_est"]))[:config.HEATMAP_PER_SECTOR]
            for t in ts:
                f = feats[t]
                heat.append({"t": t, "mk": mk, "s": sec, "m": meta[t]["mcap"] or meta[t]["mcap_est"],
                             "r1": f["r1d"], "r5": f["r5d"], "r21": f["r21"], "r63": f["r63"],
                             "a150": f["above150"], "sc": rows[t]["score"]})

    # ---- סטטיסטיקה לפי קטגוריות ----
    th = {}
    for t, x in rows.items():
        for name in {x["theme"], *x["tags"]}:
            d = th.setdefault(name, {"n": 0, "r1": [], "r5": [], "r21": [], "r63": [], "a150": 0, "top": []})
            f = x["f"]
            d["n"] += 1
            d["a150"] += int(f["above150"])
            for k, fk in (("r1", "r1d"), ("r5", "r5d"), ("r21", "r21"), ("r63", "r63")):
                if not np.isnan(f[fk]):
                    d[k].append(f[fk])
            if x["eligible"]:
                d["top"].append((x["score"], t))
    theme_stats = []
    for name, d in th.items():
        if d["n"] < 3:
            continue
        theme_stats.append({"name": name, "n": d["n"], "a150": d["a150"] / d["n"],
                            **{k: float(np.median(d[k])) if d[k] else None for k in ("r1", "r5", "r21", "r63")},
                            "leaders": [t for _, t in sorted(d["top"], reverse=True)[:5]]})
    theme_stats.sort(key=lambda d: -(d["r21"] or -9))

    # ---- רוחב שוק ----
    def breadth(ts):
        ts = [t for t in ts if t in feats]
        if not ts:
            return {}
        return {"n": len(ts), "a150": sum(feats[t]["above150"] for t in ts) / len(ts),
                "a50": sum(feats[t]["above50"] for t in ts) / len(ts),
                "nh": sum(feats[t]["new_high"] for t in ts), "nl": sum(feats[t]["price"] <= feats[t]["lo52"] * 1.02 for t in ts),
                "stage2": sum(feats[t]["stage"] == 2 for t in ts) / len(ts)}

    # ---- מעקב ביצועים של המלצות קודמות ----
    hpath = os.path.join(ROOT, "data", "picks_history.csv")
    past = []
    if os.path.exists(hpath):
        past = list(csv.DictReader(open(hpath, encoding="utf-8")))
    past = [p for p in past if p["date"] != asof]
    spy_c = spy["Close"]
    track = []
    for p in past:
        t = p["ticker"]
        if t not in feats:
            continue
        entry = float(p["price"])
        sp0 = spy_c.loc[:p["date"]]
        spy_ret = float(spy_c.iloc[-1] / sp0.iloc[-1] - 1) if len(sp0) else None
        track.append({"date": p["date"], "t": t, "rank": int(p["rank"]), "entry": entry,
                      "now": feats[t]["price"], "ret": feats[t]["price"] / entry - 1, "spy": spy_ret})
    for i, x in enumerate(picks, 1):
        past.append({"date": asof, "ticker": x["t"], "rank": i, "price": round(x["f"]["price"], 4),
                     "score": round(x["score"], 1)})
    with open(hpath, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "ticker", "rank", "price", "score"])
        w.writeheader()
        w.writerows(past)

    # ---- התיק האישי ----
    pf_rows = []
    for pz in portfolio:
        t = pz["ticker"]
        if t not in feats:
            pf_rows.append({"t": t, "status": "לא נמצאו נתונים לטיקר", "level": 0})
            continue
        f, x = feats[t], rows[t]
        price, buy = f["price"], pz["buy_price"]
        ret = price / buy - 1 if buy else None
        stop = pz["stop"] or (buy * (1 - config.DEFAULT_STOP_PCT) if buy else None)
        sig = []  # (רמה, טקסט): 3=מכירה, 2=אזהרה, 1=מידע
        if stop and price <= stop:
            sig.append((3, f"הסטופ נפגע ({stop:.2f}) – לפי הכללים: לצאת"))
        if f["stage"] == 4:
            sig.append((3, "שלב 4 – מתחת לממוצע 150 יורד (Weinstein: מכירה)"))
        elif price < f["sma150"]:
            sig.append((3, "נשברה מתחת לממוצע 150 – סימן מכירה לפי Weinstein"))
        elif price < f["sma50"]:
            sig.append((2, "מתחת לממוצע 50 – חולשה, לעקוב"))
        if x["earn"] is not None and x["earn"] <= config.EARNINGS_WARN_DAYS:
            sig.append((2, f"דוח רבעוני בעוד {max(0, x['earn'])} ימים"))
        if ret is not None and ret >= config.TAKE_PROFIT_PCT:
            sig.append((1, f"ברווח {ret * 100:.0f}% – לשקול מימוש חלקי (כלל O'Neil 20–25%)"))
        mcp = x.get("micha")
        if mcp and "שברה" in mcp["checks"][3]["note"]:
            sig.append((2, "שבר את קו המגמה העולה (שיטת מיכה: מכירה בשבירת הקו)"))
        if mcp and mcp.get("hs"):
            sig.append((2, "תבנית ראש וכתפיים – סימן היפוך"))
        if f["updown"] < 0.8:
            sig.append((2, "נפח בימי ירידה גבוה – חלוקה מוסדית"))
        if not sig:
            sig.append((0, "המגמה תקינה – להחזיק"))
        lvl = max(l for l, _ in sig)
        pf_rows.append({"t": t, "name": meta[t]["name"], "cur": "אג'" if t.endswith(".TA") else "$",
                        "buy": buy, "buy_date": pz["buy_date"], "shares": pz["shares"], "price": price,
                        "ret": ret, "r1d": f["r1d"], "stop": stop,
                        "value": price * pz["shares"] if pz["shares"] else None, "score": x["score"],
                        "rs": x["rs"], "stage": f["stage"], "ext150": f["ext_sma150"], "earn": x["earn"],
                        "signals": [t2 for _, t2 in sorted(sig, reverse=True)], "level": lvl,
                        "notes": pz["notes"]})

    # ---- ענפים מובילים ----
    ind = []
    for (mk, name), g in groups.items():
        members = [t for t in feats if gkey(t) == (mk, name)]
        ind.append({"name": name, "mk": mk, "rank": g["rank"], "of": g["of"], "n": g["n"],
                    "sector": themes.sector_he(meta[members[0]]["sector"]) if members else "",
                    "r21": float(np.nanmedian([feats[t]["r21"] for t in members])),
                    "r63": float(np.nanmedian([feats[t]["r63"] for t in members])),
                    "stage2": sum(feats[t]["stage"] == 2 for t in members) / len(members),
                    "leaders": [t for t in sorted(members, key=lambda t: -rows[t]["score"]) if rows[t]["eligible"]][:4]})
    ind.sort(key=lambda d: (d["mk"] != "US", d["rank"]))

    # ---- סיכום הבדיקה לאחור (אם רצה) ----
    bt = None
    bpath = os.path.join(ROOT, "data", "backtest.json")
    if os.path.exists(bpath):
        try:
            bt = json.load(open(bpath, encoding="utf-8"))
        except Exception:  # noqa
            bt = None

    table = [card(x) for x in ranked[:config.TABLE_N]]
    for c in table:
        c.pop("good"), c.pop("warn"), c.pop("plan")
    report = {
        "asof": asof, "generated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "runtime_min": (datetime.utcnow() - t0).total_seconds() / 60,
        "counts": {"universe": len(meta), "analyzed": len(feats), "eligible": len(elig), "fund": len(cand),
                   "us": len(us_t), "tase": len(tase_t)},
        "watch": watch_rows(wl, hist),
        "fx": fx, "weights": scoring.W, "weights_src": weights_src, "portfolio": pf_rows,
        "industries": ind, "backtest": bt,
        "regime": [regime(spy, "S&P 500 (SPY)"), regime(hist.get(config.BENCH_US2), "נאסד\"ק 100 (QQQ)"),
                   regime(ta, "ת\"א 125")],
        "breadth": {"US": breadth(us_t), "TASE": breadth(tase_t)},
        "picks": [card(x, i + 1, True) for i, x in enumerate(picks)],
        "israel": [card(x, i + 1, True) for i, x in enumerate(israel)],
        "by_cap": {k: [card(x) for x in v] for k, v in by_cap.items()},
        "table": table, "heat": heat, "themes": theme_stats, "track": track,
        "analogs": [{k: a[k] for k in ("ticker", "date", "label", "fwd6", "fwd12")} for a in lib],
    }
    report["research_url"] = getattr(config, "RESEARCH_URL", "")
    # מחירי סגירה של מניות המעקב – למודול המחקר (חישוב תגובה לאמירות)
    try:
        wt = list(dict.fromkeys(getattr(config, "WATCH_TICKERS", []) + [p["t"] for p in report["picks"]]))
        missing = [t for t in wt if t not in hist]
        extra = data.download_history(missing) if missing else {}
        wp = {}
        for t in wt:
            df = hist.get(t) if t in hist else extra.get(t)
            if df is not None and len(df):
                c = df["Close"].iloc[-130:]
                wp[t] = {str(i.date()): round(float(v), 4) for i, v in c.items()}
        json.dump({"asof": asof, "close": wp}, open(os.path.join(ROOT, "data", "watch_prices.json"), "w"), separators=(",", ":"))
    except Exception as e:  # noqa
        log(f"watch prices skipped: {e}")
    report = clean(report)
    os.makedirs(os.path.join(ROOT, "docs", "archive"), exist_ok=True)
    tpl = open(os.path.join(ROOT, "screener", "template.html"), encoding="utf-8").read()
    archive = sorted([f[:-5] for f in os.listdir(os.path.join(ROOT, "docs", "archive")) if f.endswith(".html")] + [asof],
                     reverse=True)
    report["archive"] = sorted(set(archive), reverse=True)[:60]
    payload = json.dumps(report, ensure_ascii=False).replace("</", "<\\/")
    html = tpl.replace("/*__DATA__*/null", payload)
    open(os.path.join(ROOT, "docs", "index.html"), "w", encoding="utf-8").write(html)
    open(os.path.join(ROOT, "docs", "archive", f"{asof}.html"), "w", encoding="utf-8").write(html)
    json.dump(report, open(os.path.join(ROOT, "data", "latest.json"), "w", encoding="utf-8"), ensure_ascii=False)
    log(f"done in {report['runtime_min']:.1f} min – top: {[p['t'] for p in report['picks']]}")
    return report
