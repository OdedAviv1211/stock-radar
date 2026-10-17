"""הצינור היומי: יקום ← נתונים ← אינדיקטורים ← דמיון למנצחות ← ניקוד ← בחירת 10 ← דשבורד."""
import csv
import json
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from . import news, watch, analogs, config, data, micha, patterns, scoring, themes
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


def long_term(f, fund_score=None, mcap=None):
    """אופק החזקה. 🌳 רק כשכל התנאים לטווח ארוך מתקיימים; אחרת מסומן כמסחר לטווח קצר ומפורט מה חסר."""
    if not f:
        return {"ok": False, "label": "אין נתונים", "why": "", "missing": []}
    trend = f["sma150"] > f["sma200"] and f["sma150_slope"] > 0 and f.get("sma200_slope", 0) > 0 and f["price"] > f["sma200"]
    s3 = f.get("sma200_slope3m")
    checks = [
        (trend, "ממוצע 150 מעל ממוצע 200 ושניהם עולים"),
        (s3 is not None and s3 == s3 and s3 > 0.02, "ממוצע 200 עולה כבר 3 חודשים"),
        ((f.get("r252") or 0) > 0 and (f.get("ex_ret_6m") or 0) > 0, "תשואה חיובית בשנה ועדיפות על השוק בחצי שנה"),
        (mcap is not None and mcap >= 2e9, "חברה בשווי 2 מיליארד $ לפחות"),
        (fund_score is not None and fund_score >= 60, "יסודות חזקים (צמיחה ורווחיות)"),
    ]
    missing = [t for ok, t in checks if not ok]
    if not missing:
        return {"ok": True, "label": "מתאימה גם להחזקה ארוכה", "why": "כל 5 תנאי הטווח הארוך מתקיימים", "missing": []}
    if trend and len(missing) <= 2:
        return {"ok": False, "label": "מגמה ארוכה בבנייה", "why": "חסר: " + " · ".join(missing), "missing": missing}
    return {"ok": False, "label": "מסחר לטווח קצר בלבד", "why": "חסר: " + " · ".join(missing), "missing": missing}


def exec_summary(rep):
    """קציר מנהלים: 5–7 שורות תחתונות, מהחשוב לפחות חשוב. כל שורה: {"k": כותרת, "t": טקסט, "lv": 0-3}."""
    out = []
    g = rep.get("goal")
    if g:
        lv = 0 if g["status"] in ("בקצב",) or g["status"].startswith("מקדים") else 2
        out.append({"k": "יעד ההכנסה", "lv": lv,
                    "t": f"{g['status']} · ₪{g['current_ils']:,.0f} ({g['progress_a'] * 100:.1f}% מהיעד) · צפי ~{g['base_years'] if g['base_years'] is not None else '80+'} שנים בהפקדה של ₪{g['cfg']['monthly_contrib_ils']:,}"})
    pf = rep.get("portfolio", [])
    red = sorted({p["t"] for p in pf if (p.get("level") or 0) >= 3})
    warn = sorted({p["t"] for p in pf if (p.get("level") or 0) == 2})
    add = sorted({p["t"] for p in pf if p.get("action") == "אזור הוספה"})
    conc = sorted({f"{p['t']} {p['weight'] * 100:.0f}% ({(p.get('acct') or '').split(' – ')[0].replace('תיק ', '')})" for p in pf
                   if p.get("action", "").startswith("להחזיק – לא להוסיף") and p.get("weight") is not None})
    if pf:
        parts = []
        if red:
            parts.append(f"לבחון צמצום: {', '.join(red)}")
        if conc:
            parts.append(f"משקל יתר: {', '.join(conc)}")
        if add:
            parts.append(f"אזור הוספה: {', '.join(add)}")
        if warn:
            parts.append(f"באזהרה: {', '.join(warn)}")
        out.append({"k": "התיקים שלי", "lv": 3 if red else 2 if (warn or conc) else 0,
                    "t": " · ".join(parts) or "אין שינוי – להחזיק"})
    reg = rep.get("regime", [])
    if reg:
        mn = min((r.get("level") or 0) for r in reg if r.get("status") != "לא זמין") if any(r.get("status") != "לא זמין" for r in reg) else 0
        lvl = 0 if mn >= 2 else 1 if mn >= 1 else 2 if mn >= -1 else 3
        out.append({"k": "מצב השוק", "lv": lvl, "t": " · ".join(f"{r['name'].split(' (')[0]}: {r['status']}" for r in reg)})
    pk = rep.get("picks", [])
    if pk:
        tree = [p["t"] for p in pk if (p.get("horizon") or {}).get("ok")]
        th = {}
        for p in pk:
            th[p["theme"]] = th.get(p["theme"], 0) + 1
        big = max(th.items(), key=lambda kv: kv[1])
        txt = f"מובילות: {', '.join(p['t'] for p in pk[:3])} · 🌳 לטווח ארוך: {', '.join(tree) if tree else 'אין היום'}"
        if big[1] >= 5:
            txt += f" · ⚠ ריכוז: {big[1]} מתוך {len(pk)} ב{big[0]} – הימור אחד, לא 10"
        out.append({"k": "המלצות היום", "lv": 1 if big[1] >= 5 else 0, "t": txt})
    stp = [x["t"] for x in rep.get("pick_track", []) if x.get("alert") and "מתחת לסטופ המסחר" in x["alert"]]
    if stp:
        out.append({"k": "סטופ", "lv": 2, "t": f"{len(stp)} המלצות קודמות מתחת לסטופ המסחר: {', '.join(stp[:8])} – מי שנכנס לטווח קצר: לצאת. 🌳 לטווח ארוך: לפי קו הבחינה בלבד"})
    tr = [r for r in rep.get("track", []) if r.get("spy") is not None]
    if tr:
        ex = sum(r["ret"] - r["spy"] for r in tr) / len(tr) * 100
        beat = sum(r["ret"] > r["spy"] for r in tr) / len(tr) * 100
        out.append({"k": "בקרה", "lv": 0 if ex >= 0 else 1,
                    "t": f"ההמלצות עד היום מול S&P 500: {ex:+.1f}% בממוצע · {beat:.0f}% ניצחו את המדד ({len(tr)} המלצות)"})
    todo = []
    if red:
        todo.append(f"לבחון צמצום ב-{', '.join(red[:3])}")
    if add:
        todo.append(f"לשקול הוספה ב-{', '.join(add[:3])}")
    if stp:
        todo.append("לממש פוזיציות מסחר מתחת לסטופ")
    out.insert(0, {"k": "מה לעשות היום", "lv": 3 if red else 1 if todo else 0,
                   "t": " · ".join(todo) if todo else "אין פעולה נדרשת – להחזיק לפי התוכנית"})
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
        if (t in benches and not meta.get(t, {}).get("pf_only")) or t not in meta:
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
            (mk != "US" or f["price"] >= config.US_MIN_PRICE) and not meta[t].get("pf_only")
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
    picks, per_theme, per_ind = [], {}, {}
    for x in ranked:
        if meta[x["t"]]["market"] != "US" and len([p for p in picks if meta[p["t"]]["market"] != "US"]) >= 2:
            continue
        if per_theme.get(x["theme"], 0) >= config.MAX_PER_THEME:
            continue
        ind_k = meta[x["t"]].get("industry") or x.get("sub") or x["theme"]
        if per_ind.get(ind_k, 0) >= getattr(config, "MAX_PER_INDUSTRY", 99):
            continue
        picks.append(x)
        per_theme[x["theme"]] = per_theme.get(x["theme"], 0) + 1
        per_ind[ind_k] = per_ind.get(ind_k, 0) + 1
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
        o["horizon"] = long_term(f, x["parts"].get("fund") if x.get("info") else None, m.get("mcap") or m.get("mcap_est"))
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
    # ---- כלל יציאה: המלצות מ-30 הימים האחרונים ----
    exits = []
    try:
        cut = (pd.Timestamp(asof) - pd.Timedelta(days=config.EXIT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        first = {}
        for p_ in past:
            if p_["date"] >= cut:
                first.setdefault(p_["ticker"], p_)
        cur = {x["t"] for x in picks}
        for t, p_ in first.items():
            df = hist.get(t)
            if df is None or not len(df):
                continue
            c = df["Close"]
            since = c.loc[p_["date"]:]
            if not len(since):
                continue
            peak, now = float(since.max()), float(c.iloc[-1])
            sma20 = float(c.iloc[-20:].mean())
            dd = now / peak - 1
            why = []
            if dd <= -config.EXIT_DD:
                why.append(f"ירדה {abs(dd)*100:.0f}% מהשיא מאז ההמלצה")
            if now < sma20:
                why.append("נסגרה מתחת לממוצע 20 יום")
            exits.append({"t": t, "since": p_["date"], "entry": float(p_["price"]), "peak": peak, "now": now,
                          "ret": now / float(p_["price"]) - 1, "dd": dd, "exit": bool(why), "why": why,
                          "in_top": t in cur})
        exits.sort(key=lambda e: (not e["exit"], e["dd"]))
    except Exception as e:  # noqa
        log(f"exits skipped: {e}")
    # ---- יומן מעקב המלצות: לכל מניה שהומלצה ב-60 הימים האחרונים – ציון, דירוג, סיבת יציאה וסטופים ----
    pick_track = []
    try:
        PART_HE = {"trend": "מגמה", "rs": "חוזק יחסי", "analog": "דמיון למנצחות", "fund": "יסודות",
                   "group": "חוזק הענף", "accum": "איסוף מוסדי", "setup": "נקודת כניסה"}
        lpath = os.path.join(ROOT, "data", "pick_log.csv")
        log_rows = list(csv.DictReader(open(lpath, encoding="utf-8"))) if os.path.exists(lpath) else []
        log_rows = [r for r in log_rows if r["date"] != asof]
        cut60 = (pd.Timestamp(asof) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
        tracked = {}
        for p_ in past:
            if p_["date"] >= cut60:
                tracked.setdefault(p_["ticker"], p_)
        top_rank = {x["t"]: i for i, x in enumerate(picks, 1)}
        for x in picks:
            tracked.setdefault(x["t"], {"date": asof, "price": x["f"]["price"]})
        cutoff = picks[-1]["score"] if picks else None
        overall = {x["t"]: i for i, x in enumerate(ranked, 1)}
        for t, p_ in tracked.items():
            r_ = rows.get(t)
            f = feats.get(t)
            if not r_ or not f:
                reason = "אין נתונים היום"
            elif t in top_rank:
                reason = "בטופ 10"
            elif not r_["eligible"]:
                why = []
                if f["stage"] != 2:
                    why.append("יצאה משלב 2 – המגמה העולה נשברה")
                if f["sma150_slope"] <= 0:
                    why.append("ממוצע 150 הפסיק לעלות")
                if f["price"] < config.US_MIN_PRICE and not t.endswith(".TA"):
                    why.append("מחיר נמוך מהסף")
                reason = " · ".join(why) or "לא עומדת בתנאי הסף (נזילות)"
            elif t not in cand_set:
                reason = "לא עברה את סינון היסודות"
            elif cutoff is not None and r_["score"] >= cutoff:
                reason = "ציון מספיק, אבל נחסמה בתקרת הענף/הקטגוריה (פיזור)"
            else:
                reason = f"הציון ירד מתחת לסף הכניסה ({cutoff:.0f})" if cutoff is not None else "מחוץ לטופ"
            c = hist[t]["Close"] if t in hist else None
            since = c.loc[p_["date"]:] if c is not None else None
            peak = float(since.max()) if since is not None and len(since) else None
            entry = float(p_["price"])
            stop_trade = max(entry * (1 - config.EXIT_DD), peak * (1 - config.EXIT_DD)) if peak else entry * (1 - config.EXIT_DD)
            line_long = f["sma200"] * (1 - config.REVIEW_BELOW_SMA200) if f else None
            sp0 = spy["Close"].loc[:p_["date"]]
            spy_ret = float(spy["Close"].iloc[-1] / sp0.iloc[-1] - 1) if len(sp0) else None
            log_rows.append({"date": asof, "ticker": t, "in_top": int(t in top_rank), "rank": top_rank.get(t, ""),
                             "overall": overall.get(t, ""), "score": round(r_["score"], 1) if r_ else "",
                             "cutoff": round(cutoff, 1) if cutoff is not None else "",
                             "price": round(f["price"], 4) if f else "", "reason": reason,
                             "parts": json.dumps({k: round(v, 1) for k, v in r_["parts"].items()}) if r_ else ""})
            hist_t = [r for r in log_rows if r["ticker"] == t]
            seen_d = {r["date"] for r in hist_t}
            hist_t += [{"date": q["date"], "score": q["score"], "in_top": 1, "parts": ""}
                       for q in past if q["ticker"] == t and q["date"] not in seen_d and q["date"] >= cut60]
            first_parts = next((json.loads(r["parts"]) for r in hist_t if r.get("parts")), None)
            moved = []
            if first_parts and r_:
                d_ = {k: r_["parts"][k] - first_parts.get(k, r_["parts"][k]) for k in r_["parts"]}
                moved = [f"{PART_HE.get(k, k)} {v:+.0f}" for k, v in sorted(d_.items(), key=lambda kv: kv[1])[:2] if v < -2]
                moved += [f"{PART_HE.get(k, k)} {v:+.0f}" for k, v in sorted(d_.items(), key=lambda kv: -kv[1])[:1] if v > 2]
            now = f["price"] if f else None
            status = "in" if t in top_rank else "out"
            alert = []
            if now and now <= stop_trade:
                alert.append("מתחת לסטופ המסחר")
            if f and now < f["sma20"]:
                alert.append("מתחת לממוצע 20")
            if line_long and now and now < line_long:
                alert.append("מתחת לקו הבחינה לטווח ארוך")
            pick_track.append({"t": t, "first": p_["date"], "horizon": long_term(f, r_["parts"].get("fund") if r_ and r_.get("info") else None, (meta.get(t) or {}).get("mcap") or (meta.get(t) or {}).get("mcap_est")), "entry": entry, "now": now, "peak": peak,
                               "ret": (now / entry - 1) if now else None, "spy": spy_ret,
                               "dd": (now / peak - 1) if now and peak else None, "status": status, "reason": reason,
                               "stop_trade": stop_trade, "sma20": f["sma20"] if f else None, "line_long": line_long,
                               "moved": moved, "alert": alert,
                               "scores": [[r["date"], float(r["score"]) if r["score"] not in ("", None) else None, int(r["in_top"])]
                                          for r in sorted(hist_t, key=lambda r: r["date"])][-20:]})
        pick_track.sort(key=lambda x: (x["status"] != "in", x["first"]))
        with open(lpath, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["date", "ticker", "in_top", "rank", "overall", "score", "cutoff", "price", "reason", "parts"])
            w.writeheader()
            w.writerows([r for r in log_rows if r["date"] >= cut60])
    except Exception as e:  # noqa
        log(f"pick tracking skipped: {e}")
    for i, x in enumerate(picks, 1):
        past.append({"date": asof, "ticker": x["t"], "rank": i, "price": round(x["f"]["price"], 4),
                     "score": round(x["score"], 1)})
    with open(hpath, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "ticker", "rank", "price", "score"])
        w.writeheader()
        w.writerows(past)

    # ---- התיקים (נקודת מוצא: החזקה לטווח ארוך) ----
    pf_rows = []
    acc_val = {}
    for pz in portfolio:
        t = pz["ticker"]
        if t in feats and pz["shares"]:
            acc_val[pz["notes"]] = acc_val.get(pz["notes"], 0) + feats[t]["price"] * pz["shares"]
    for pz in portfolio:
        t = pz["ticker"]
        acc = config.ACCOUNTS.get(pz["notes"], {"label": pz["notes"] or "תיק", "max_weight": 0.25, "type": "long"})
        if t not in feats:
            pf_rows.append({"t": t, "status": "לא נמצאו נתונים לטיקר", "level": 0, "notes": pz["notes"], "acct": acc["label"]})
            continue
        f, x = feats[t], rows[t]
        price, buy = f["price"], pz["buy_price"]
        ret = price / buy - 1 if buy else None
        value = price * pz["shares"] if pz["shares"] else None
        weight = value / acc_val[pz["notes"]] if value and acc_val.get(pz["notes"]) else None
        sma200 = f["sma200"] if f.get("sma200") and not np.isnan(f["sma200"]) else f["sma150"]
        review = pz["stop"] or sma200 * (1 - config.REVIEW_BELOW_SMA200)
        mc = meta[t].get("mcap")
        spec = price < config.SPEC_PRICE or (mc is not None and mc < config.SPEC_MCAP)
        up = f["stage"] == 2
        sig = []  # (רמה, טקסט): 3=לבחון יציאה, 2=אזהרה, 1=מידע, 0=תקין
        if pz["stop"] and price <= pz["stop"]:
            sig.append((3, f"הסטופ שהגדרת ({pz['stop']:.2f}) נפגע – לבחון יציאה"))
        if f["stage"] == 4 and price < review:
            sig.append((3, f"שבירה ארוכת טווח: שלב 4 ומתחת לקו הבחינה {review:.2f} – לבחון צמצום"
                           + (" (מניה ספקולטיבית – לא להוסיף)" if spec else "")))
        elif price < sma200:
            sig.append((2, f"מתחת לממוצע 200 ({sma200:.2f}) – לבחון, לא למכור אוטומטית בתיק ארוך טווח"))
        elif price < f["sma50"]:
            sig.append((1, "תיקון בתוך מגמה ארוכה – מתחת לממוצע 50"))
        if weight is not None and weight > acc["max_weight"]:
            sig.append((2, f"ריכוזיות: {weight * 100:.0f}% מהתיק (תקרה {acc['max_weight'] * 100:.0f}%) – לשקול איזון הדרגתי"))
        if spec and weight is not None and weight > config.SPEC_MAX_WEIGHT:
            sig.append((2, f"ספקולטיבית ב-{weight * 100:.0f}% מהתיק – מעל תקרה של {config.SPEC_MAX_WEIGHT * 100:.0f}%"))
        if x["earn"] is not None and x["earn"] <= config.EARNINGS_WARN_DAYS:
            sig.append((1, f"דוח רבעוני בעוד {max(0, x['earn'])} ימים – לא להוסיף לפני הדוח"))
        mcp = x.get("micha")
        if mcp and mcp.get("hs"):
            sig.append((2, "תבנית ראש וכתפיים – סימן היפוך"))
        # פעולה מומלצת לטווח ארוך
        d20, d50 = price / f["sma20"] - 1 if f.get("sma20") else None, price / f["sma50"] - 1
        if any(l >= 3 for l, _ in sig):
            action = "לבחון צמצום"
        elif weight is not None and weight > acc["max_weight"]:
            action = "להחזיק – לא להוסיף (לאזן)"
        elif up and not spec and (0 <= d50 <= 0.04 or (d20 is not None and 0 <= d20 <= 0.02)):
            action = "אזור הוספה"
            sig.append((0, "מגמה עולה ותיקון לממוצע 20/50 – נקודת הוספה לטווח ארוך"))
        elif up and f["ext_sma150"] > 0.40:
            action = "להחזיק – מתוחה, להוסיף רק בתיקון"
        elif price < sma200:
            action = "להחזיק בזהירות"
        else:
            action = "להחזיק"
        if not sig:
            sig.append((0, "המגמה הארוכה תקינה – להחזיק"))
        lvl = max(l for l, _ in sig)
        pf_rows.append({"t": t, "name": meta[t]["name"], "cur": "אג'" if t.endswith(".TA") else "$",
                        "buy": buy, "buy_date": pz["buy_date"], "shares": pz["shares"], "price": price,
                        "ret": ret, "r1d": f["r1d"], "stop": review, "review": review, "sma200": sma200,
                        "value": value, "weight": weight, "spec": spec, "action": action, "score": x["score"],
                        "rs": x["rs"], "stage": f["stage"], "ext150": f["ext_sma150"], "earn": x["earn"],
                        "signals": [t2 for _, t2 in sorted(sig, key=lambda z: -z[0])], "level": lvl,
                        "notes": pz["notes"], "acct": acc["label"]})

    comp_labels = {v["label"] for v in config.ACCOUNTS.values() if v["type"] == "company"}
    pf_rows.sort(key=lambda r: 0 if r.get("acct") in comp_labels else 1)

    # ---- יעד: הכנסה חודשית מתיק החברה + תוכנית לתיק האישי ----
    goal = None
    try:
        G = config.GOAL
        val_ils = lambda typ: sum(acc_val.get(k, 0) for k, v in config.ACCOUNTS.items() if v["type"] == typ) * fx
        cur = val_ils("company")
        net_y = G["monthly_net_ils"] * 12
        need = {"a": net_y / (1 - G["tax_simple"]) / G["withdraw_rate"],
                "b": net_y / ((1 - G["tax_corp"]) * (1 - G["tax_div"])) / G["withdraw_rate"]}

        def fv(v0, r, c, months):
            rm = (1 + r) ** (1 / 12) - 1
            return v0 * (1 + rm) ** months + (c * ((1 + rm) ** months - 1) / rm if rm else c * months)

        def years(target, r, c):
            v, n = cur, 0
            while v < target and n < 80 * 12:
                v = fv(v, r, c, 1)
                n += 1
            return round(n / 12, 1) if v >= target else None

        grid = [{"contrib": c, "rows": [{"r": r, "a": years(need["a"], r, c), "b": years(need["b"], r, c)}
                                        for r in G["returns"]]} for c in G["contrib_grid"]]
        d0 = datetime.strptime(G["start_date"], "%Y-%m-%d")
        months = max(0, (datetime.utcnow() - d0).days / 30.44)
        planned = fv(G["start_value_ils"], G["base_return"], G["monthly_contrib_ils"], months)
        gap = cur / planned - 1 if planned else 0
        status = "מקדים את התוכנית" if gap > 0.03 else "מפגר אחרי התוכנית" if gap < -0.03 else "בקצב"
        base_y = years(need["a"], G["base_return"], G["monthly_contrib_ils"])
        goal = {"current_ils": cur, "need_a": need["a"], "need_b": need["b"], "progress_a": cur / need["a"],
                "progress_b": cur / need["b"], "grid": grid, "cfg": G, "planned_ils": planned, "gap": gap,
                "status": status, "base_years": base_y,
                "base_year": (d0.year + base_y) if base_y else None}
        P = config.PERSONAL_PLAN
        pcur = val_ils("long")
        p0 = datetime.strptime(P["start_date"], "%Y-%m-%d")
        pm = max(0, (datetime.utcnow() - p0).days / 30.44)
        left = max(0, P["years"] * 12 - pm)
        goal["personal"] = {"current_ils": pcur, "contrib": P["monthly_contrib_ils"], "years": P["years"],
                            "end_year": p0.year + P["years"],
                            "planned_ils": fv(P["start_value_ils"], G["base_return"], P["monthly_contrib_ils"], pm),
                            "grid": [{"contrib": c, "fv": [fv(pcur, r, c, left) for r in P["returns"]]}
                                     for c in P["contrib_grid"]], "returns": P["returns"]}
    except Exception as e:  # noqa
        log(f"goal skipped: {e}")

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
        "goal": goal, "fx": fx, "weights": scoring.W, "weights_src": weights_src, "portfolio": pf_rows,
        "industries": ind, "backtest": bt,
        "regime": [regime(spy, "S&P 500 (SPY)"), regime(hist.get(config.BENCH_US2), "נאסד\"ק 100 (QQQ)"),
                   regime(ta, "ת\"א 125")],
        "breadth": {"US": breadth(us_t), "TASE": breadth(tase_t)},
        "picks": [card(x, i + 1, True) for i, x in enumerate(picks)],
        "israel": [card(x, i + 1, True) for i, x in enumerate(israel)],
        "by_cap": {k: [card(x) for x in v] for k, v in by_cap.items()},
        "table": table, "heat": heat, "themes": theme_stats, "track": track, "exits": exits, "pick_track": pick_track,
        "analogs": [{k: a[k] for k in ("ticker", "date", "label", "fwd6", "fwd12")} for a in lib],
    }
    report["research_url"] = getattr(config, "RESEARCH_URL", "")
    # ---- הרחבה: מקומות 11–20 לפי ציון ----
    try:
        top_set = {x["t"] for x in picks}
        ext = [x for x in ranked if x["t"] not in top_set and meta[x["t"]]["market"] == "US"][:getattr(config, "TOP_N_EXT", 20) - len(picks)]
        report["picks_ext"] = [card(x, len(picks) + i + 1) for i, x in enumerate(ext)]
    except Exception as e:  # noqa
        log(f"ext picks skipped: {e}")
        report["picks_ext"] = []
    # ---- קציר מנהלים: שורות תחתונות ----
    try:
        report["exec"] = exec_summary(report)
    except Exception as e:  # noqa
        log(f"exec summary skipped: {e}")
        report["exec"] = []
    # ---- מה נאמר: דיווחים רשמיים + תקשורת מובילה, מול מצב הגרף ----
    try:
        nt = [r["t"] for r in pf_rows] + [p["t"] for p in report["picks"]] + [w["t"] for w in report["watch"]]
        tech = {t: bool(feats[t]["price"] > feats[t]["sma150"] and feats[t]["sma150_slope"] > 0)
                for t in nt if t in feats}
        for w in report["watch"]:
            if "uptrend" in w:
                tech[w["t"]] = w["uptrend"]
        report["news"] = news.collect(nt, tech)
    except Exception as e:  # noqa
        log(f"news skipped: {e}")
        report["news"] = {}
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
    # תקציר קטן לקריאה מהירה (טלגרם / Claude)
    summ = {"asof": asof, "generated": report["generated"], "weights_src": weights_src,
            "regime": [f"{r['name']}: {r['status']}" for r in report["regime"]],
            "picks": [[p["t"], round(p["score"]), p["theme"]] for p in report["picks"]],
            "israel": [[p["t"], round(p["score"])] for p in report["israel"]],
            "exec": [f"{x['k']}: {x['t']}" for x in report.get("exec", [])],
            "exits": [[e["t"], round(e["ret"] * 100, 1), round(e["dd"] * 100, 1), e["why"]] for e in report.get("exits", []) if e["exit"]],
            "track": (lambda tr: {"n": len(tr), "avg": round(sum(r["ret"] for r in tr) / len(tr) * 100, 2),
                                  "ex_spy": round(sum(r["ret"] - r["spy"] for r in tr if r["spy"] is not None) / max(1, sum(r["spy"] is not None for r in tr)) * 100, 2),
                                  "beat": round(sum(r["spy"] is not None and r["ret"] > r["spy"] for r in tr) / len(tr) * 100)} if tr else None)(report.get("track", [])),
            "portfolio": [[r["t"], r.get("notes", ""), r.get("level"), (r.get("signals") or [r.get("status")])[0],
                           None if r.get("ret") is None else round(r["ret"] * 100, 1)] for r in pf_rows],
            "watch": [[w["t"], w.get("action"), [e["text"] for e in w.get("events", [])]] for w in report["watch"]],
            "news": {t: v["verdict"] for t, v in report.get("news", {}).items()}}
    json.dump(summ, open(os.path.join(ROOT, "data", "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    log(f"done in {report['runtime_min']:.1f} min – top: {[p['t'] for p in report['picks']]}")
    return report
