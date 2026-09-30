"""בדיקה לאחור + כיול משקלות.

מה נבדק: בכל "יום החלפה" (כל ~חודש) ב-8 השנים האחרונות, השיטה מחשבת את אותם ציונים בדיוק
מהנתונים שהיו ידועים באותו יום, בוחרת 10 מניות, ומודדת מה הן עשו בחודש ובשלושת החודשים שאחרי – מול S&P 500.

מגבלות חשובות (מוצגות גם בדשבורד):
* הטיית שורדים – היקום הוא המניות שנסחרות היום; חברות שנמחקו/פשטו רגל לא נכללות, וזה מנפח תוצאות.
* אין נתונים פונדמנטליים היסטוריים בחינם – רכיב ה-fund קבוע (50) בבדיקה.
* תבניות גרף לא נבדקות (חישוב כבד); רכיב ה-setup כולל פיבוט, VCP ופריצה.
* אין עמלות/החלקה. התשואות הן לפני מס.

הכיול: מחלקים את התקופה ל-65% "אימון" ו-35% "מבחן". מחפשים משקלות שממקסמים את התשואה העודפת באימון,
ומאמצים אותם (בחצי הדרך מברירת המחדל, כדי לא "להתאים יתר") רק אם הם משפרים גם בתקופת המבחן שלא ראו."""
import json
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from . import analogs, config, data
from .indicators import ANALOG_FEATURES, compute

ROOT = data.ROOT
log = data.log
COMPS = ["trend", "rs", "fund", "group", "analog", "setup", "accum"]


def _wide(hist, field, idx):
    return pd.DataFrame({t: df[field] for t, df in hist.items()}).reindex(idx).astype("float32")


def _pct_rank(df):
    return df.rank(axis=1, pct=True) * 98 + 1


def build_panel(hist, meta, spy, lib_full):
    """מחשב את כל הרכיבים בכל יום החלפה. מחזיר DataFrame ארוך: date, ticker, רכיבים, תשואות עתידיות."""
    idx = spy.index
    C = _wide(hist, "Close", idx)
    H = _wide(hist, "High", idx).fillna(C)
    L = _wide(hist, "Low", idx).fillna(C)
    V = _wide(hist, "Volume", idx).fillna(0)
    spc = spy["Close"].reindex(idx)

    start_i = 260
    reb = list(range(start_i, len(idx) - 1, config.BT_REBALANCE))
    rdates = idx[reb]
    F = {}

    def keep(name, frame):
        F[name] = frame.iloc[reb]

    s50, s150, s200 = C.rolling(50).mean(), C.rolling(150).mean(), C.rolling(200).mean()
    slope150 = s150 / s150.shift(20) - 1
    slope200 = s200 / s200.shift(21) - 1
    hi52 = H.rolling(252, min_periods=200).max()
    lo52 = L.rolling(252, min_periods=200).min()
    R = {n: C / C.shift(n) - 1 for n in (63, 126, 189, 252)}
    rs_raw = 0.4 * R[63] + 0.2 * R[126] + 0.2 * R[189] + 0.2 * R[252]
    b63, b126 = spc / spc.shift(63) - 1, spc / spc.shift(126) - 1
    keep("rs_raw", rs_raw)
    keep("ex_ret_3m", (1 + R[63]).div(1 + b63, axis=0) - 1)
    keep("ex_ret_6m", (1 + R[126]).div(1 + b126, axis=0) - 1)
    keep("dist_hi", C / hi52 - 1)
    keep("above_lo", C / lo52 - 1)
    keep("ext_sma150", C / s150 - 1)
    keep("ext_sma50", C / s50 - 1)
    keep("sma150_slope", slope150)
    keep("sma50_vs_150", s50 / s150 - 1)
    tt = ((C > s150) & (C > s200)).astype(int) + (s150 > s200).astype(int) + (slope200 > 0).astype(int) + \
        ((s50 > s150) & (s50 > s200)).astype(int) + (C > s50).astype(int) + (C >= 1.3 * lo52).astype(int) + \
        (C >= 0.75 * hi52).astype(int)
    keep("tt7", tt)
    keep("stage2", ((C > s150) & (slope150 > 0)).astype(int))
    del s50, s200, slope200, tt
    rets = C.pct_change()
    keep("vol_contract", rets.rolling(10).std() / rets.rolling(60).std())
    d = C.diff()
    upv = V.where(d > 0, 0).rolling(50).sum()
    dnv = V.where(d < 0, 0).rolling(50).sum()
    keep("updown", (upv / dnv.replace(0, np.nan)).fillna(2.0))
    v50 = V.rolling(50).mean()
    keep("vol_surge", V.rolling(20).mean() / V.rolling(100).mean())
    a_, b_, c_ = H - L, (H - C.shift()).abs(), (L - C.shift()).abs()
    tr = a_.where(a_ >= b_, b_)
    tr = tr.where(tr >= c_, c_)
    del a_, b_, c_
    keep("atr_pct", tr.rolling(20).mean() / C)
    pivot = H.shift(1).rolling(60).max()
    keep("dist_pivot", C / pivot - 1)
    keep("breakout", ((C > pivot) & (V > 1.4 * v50)).astype(int))
    keep("dollar_vol", (C * V).rolling(20).mean())
    keep("price", C)
    fwd21 = C.shift(-21) / C - 1
    fwd63 = C.shift(-63) / C - 1
    keep("fwd21", fwd21)
    keep("fwd63", fwd63)
    spy21 = (spc.shift(-21) / spc - 1).iloc[reb]
    spy63 = (spc.shift(-63) / spc - 1).iloc[reb]
    del C, H, L, V, rets, d, upv, dnv, tr, pivot, fwd21, fwd63

    # ---- רכיבים, תאריך אחר תאריך ----
    groups = pd.Series({t: (meta[t].get("industry") or meta[t].get("sector") or "אחר") for t in F["price"].columns})
    out = []
    for k, dt in enumerate(rdates):
        row = pd.DataFrame({name: fr.iloc[k] for name, fr in F.items()})
        row = row[row["price"].notna() & row["rs_raw"].notna()]
        if len(row) < 50:
            continue
        rs = row["rs_raw"].rank(pct=True) * 98 + 1
        g = groups.reindex(row.index)
        gmed = row["rs_raw"].groupby(g).median()
        gcnt = row["rs_raw"].groupby(g).size()
        gmed = gmed[gcnt >= 3]
        grank = (gmed.rank(pct=True) * 100).reindex(g.values).fillna(50).values
        elig = (row["stage2"] == 1) & (row["dollar_vol"] >= config.US_MIN_DOLLAR_VOL) & (row["price"] >= config.US_MIN_PRICE)
        r = row[elig].copy()
        if len(r) < config.BT_TOP * 2:
            out.append(pd.DataFrame({"date": [dt], "empty": [True]}))
            continue
        rsr = rs[elig]
        comp = pd.DataFrame(index=r.index)
        comp["rs"] = rsr
        comp["trend"] = ((r["tt7"] + (rsr >= 70).astype(int)) / 8 * 85 + 15).clip(0, 100)
        comp["group"] = pd.Series(grank, index=row.index)[elig]
        a = ((r["updown"] - 0.7) / 1.1).clip(0, 1)
        b = ((r["vol_surge"] - 0.8) / 1.0).clip(0, 1)
        comp["accum"] = 100 * (0.7 * a + 0.3 * b)
        dp = r["dist_pivot"]
        p = np.where((dp >= -0.06) & (dp <= 0.03), 1.0,
                     np.where(dp < -0.06, np.clip(1 - (-0.06 - dp) / 0.2, 0, 1), np.clip(1 - (dp - 0.03) / 0.15, 0.35, 1)))
        tt_ = ((1.1 - r["vol_contract"]) / 0.6).clip(0, 1).fillna(0)
        e = np.where(r["ext_sma50"] < 0.15, 1.0, np.clip(1 - (r["ext_sma50"] - 0.15) / 0.25, 0, 1))
        comp["setup"] = np.minimum(100, 100 * (0.5 * p + 0.3 * tt_ + 0.2 * e) + 10 * r["breakout"])
        comp["fund"] = 50.0
        # דמיון – רק למנצחות שהריצה שלהן כבר הסתיימה לפני התאריך (בלי "הצצה לעתיד")
        lib = [x for x in lib_full if pd.Timestamp(x["date"]) + timedelta(days=370) < dt]
        if lib:
            M = row[ANALOG_FEATURES]
            med = M.median()
            iqr = ((M.quantile(0.75) - M.quantile(0.25)).replace(0, np.nan).fillna(1.0)) / 1.35
            Z = ((r[ANALOG_FEATURES] - med) / iqr).clip(-3, 3).fillna(0).values
            LZ = ((pd.DataFrame([x["vec"] for x in lib]) - med) / iqr).clip(-3, 3).fillna(0).values
            dist = np.sqrt(((Z[:, None, :] - LZ[None, :, :]) ** 2).sum(axis=2)).min(axis=1)
            comp["analog"] = 100 * np.exp(-(dist / 3.0) ** 2)
        else:
            comp["analog"] = 50.0
        comp["fwd21"] = r["fwd21"]
        comp["fwd63"] = r["fwd63"]
        comp["spy21"] = spy21.iloc[k]
        comp["spy63"] = spy63.iloc[k]
        comp["grp"] = g[elig].values
        comp["date"] = dt
        comp["ticker"] = comp.index
        out.append(comp.reset_index(drop=True))
    panel = pd.concat(out, ignore_index=True)
    if "empty" in panel:
        panel = panel[panel["empty"].isna()].drop(columns="empty")
    return panel


_PREP = {}


def _prep(panel):
    key = id(panel)
    if key not in _PREP:
        items = []
        for dt, g in panel.groupby("date"):
            items.append((dt, g[COMPS].to_numpy(dtype=float), g["grp"].to_numpy(), g["fwd21"].to_numpy(dtype=float),
                          g["fwd63"].to_numpy(dtype=float), float(g["spy21"].iloc[0]), float(g["spy63"].iloc[0]),
                          g["ticker"].to_numpy()))
        _PREP.clear()
        _PREP[key] = items
    return _PREP[key]


def simulate(panel, weights, dates=None):
    """תיק של 10 המניות המובילות, מוחלף כל חודש (עד 3 מאותו ענף). מחזיר סדרת תשואות חודשיות."""
    w = np.array([weights[c] for c in COMPS])
    rows = []
    for dt, M, grp, f21, f63, s21, s63, tick in _prep(panel):
        if dates is not None and dt not in dates:
            continue
        order = np.argsort(-(M @ w), kind="stable")
        picks, per = [], {}
        for i in order:
            gk = grp[i]
            if per.get(gk, 0) >= 3:
                continue
            picks.append(i)
            per[gk] = per.get(gk, 0) + 1
            if len(picks) == config.BT_TOP:
                break
        r21 = f21[picks]
        r21 = r21[~np.isnan(r21)]
        r63 = f63[picks]
        r63 = r63[~np.isnan(r63)]
        rows.append({"date": dt, "ret": float(r21.mean()) if len(r21) else np.nan, "spy": s21,
                     "ret63": float(r63.mean()) if len(r63) else np.nan, "spy63": s63,
                     "hit": float((r21 > s21).mean()) if len(r21) else np.nan, "tickers": list(tick[picks])})
    return pd.DataFrame(rows).dropna(subset=["ret", "spy"])


def stats(sim):
    if sim.empty:
        return {}
    n = len(sim)
    per_year = 252 / config.BT_REBALANCE
    eq = (1 + sim["ret"]).cumprod()
    sp = (1 + sim["spy"]).cumprod()
    dd = float((eq / eq.cummax() - 1).min())
    return {"months": n, "cagr": float(eq.iloc[-1] ** (per_year / n) - 1), "spy_cagr": float(sp.iloc[-1] ** (per_year / n) - 1),
            "total": float(eq.iloc[-1] - 1), "spy_total": float(sp.iloc[-1] - 1),
            "excess_m": float((sim["ret"] - sim["spy"]).mean()), "beat_rate": float((sim["ret"] > sim["spy"]).mean()),
            "hit": float(sim["hit"].mean()), "max_dd": dd,
            "spy_dd": float((sp / sp.cummax() - 1).min()),
            "ex63": float((sim["ret63"] - sim["spy63"]).mean()) if sim["ret63"].notna().any() else None,
            "vol": float(sim["ret"].std() * np.sqrt(per_year))}


def info_coef(panel):
    """IC – מתאם דירוג ממוצע בין כל רכיב לתשואה ב-3 החודשים הבאים (כמה הרכיב 'מנבא')."""
    res = {}
    for c in COMPS:
        vals = []
        for _, g in panel.groupby("date"):
            g = g.dropna(subset=["fwd63"])
            if len(g) > 20 and g[c].nunique() > 1:
                vals.append(g[c].rank().corr(g["fwd63"].rank()))
        res[c] = float(np.nanmean(vals)) if vals else None
    return res


def calibrate(panel, rng=np.random.default_rng(42)):
    dates = sorted(panel["date"].unique())
    cut = int(len(dates) * 0.65)
    train, test = set(dates[:cut]), set(dates[cut:])
    base = dict(config.WEIGHTS)
    free = [c for c in COMPS if c != "fund"]  # fund לא נבדק היסטורית – נשאר קבוע
    budget = 1 - base["fund"]

    def objective(w, ds):
        s = simulate(panel, w, ds)
        return float((s["ret"] - s["spy"]).mean()) if len(s) else -1

    best_w, best = base, objective(base, train)
    tried = 0
    for _ in range(config.BT_TRIALS):
        x = rng.dirichlet(np.ones(len(free)))
        w = {c: float(v * budget) for c, v in zip(free, x)}
        w["fund"] = base["fund"]
        o = objective(w, train)
        tried += 1
        if o > best:
            best, best_w = o, w
    blended = {c: round(0.5 * base[c] + 0.5 * best_w[c], 4) for c in COMPS}
    t_base, t_blend = objective(base, test), objective(blended, test)
    adopted = t_blend > t_base
    log(f"calibration: train best {best:.4f}; test base {t_base:.4f} vs blended {t_blend:.4f} → adopted={adopted}")
    return {"weights": blended if adopted else base, "candidate": blended, "adopted": adopted, "trials": tried,
            "train_excess_best": best, "test_excess_base": t_base, "test_excess_blend": t_blend,
            "train_end": str(pd.Timestamp(dates[cut - 1]).date()), "test_start": str(pd.Timestamp(dates[cut]).date())}


def run():
    t0 = datetime.utcnow()
    us = [x for x in data.us_universe() if (x["mcap"] or 0) >= config.BT_MIN_MCAP or x["mcap"] is None]
    meta = {x["ticker"]: x for x in us}
    start = (datetime.utcnow() - timedelta(days=int(365.25 * (config.BT_YEARS + 1.2)))).strftime("%Y-%m-%d")
    hist = data.download_history(list(meta) + [config.BENCH_US], start=start)
    spy = hist.pop(config.BENCH_US)
    hist = {t: df for t, df in hist.items() if t in meta and len(df) > 300}
    log(f"backtest universe {len(hist)} tickers from {start}")
    win_t = sorted({w[0] for w in analogs.WINNERS})
    whist = data.download_history(win_t + [config.BENCH_US], start="2014-01-01")
    lib = analogs.build_library(whist, whist.get(config.BENCH_US, spy)["Close"])
    panel = build_panel(hist, meta, spy, lib)
    log(f"panel rows {len(panel)}, dates {panel['date'].nunique()}")

    base = dict(config.WEIGHTS)
    cal = calibrate(panel)
    sim_base = simulate(panel, base)
    sim_cal = simulate(panel, cal["candidate"])
    ic = info_coef(panel)

    def curve(sim):
        return {"d": [str(pd.Timestamp(x).date()) for x in sim["date"]],
                "s": [round(float(x), 4) for x in (1 + sim["ret"]).cumprod()],
                "b": [round(float(x), 4) for x in (1 + sim["spy"]).cumprod()]}

    last = sim_base.iloc[-1] if len(sim_base) else None
    out = {"date": datetime.utcnow().strftime("%Y-%m-%d"), "years": config.BT_YEARS, "universe": len(hist),
           "rebalance": config.BT_REBALANCE, "top": config.BT_TOP,
           "base": {"weights": base, "stats": stats(sim_base), "curve": curve(sim_base)},
           "calibrated": {"weights": cal["candidate"], "stats": stats(sim_cal), "curve": curve(sim_cal)},
           "calibration": {k: v for k, v in cal.items() if k != "weights"}, "ic": ic,
           "last_picks": {"date": str(pd.Timestamp(last["date"]).date()), "tickers": last["tickers"]} if last is not None else None,
           "runtime_min": (datetime.utcnow() - t0).total_seconds() / 60}
    from .pipeline import clean
    out = clean(out)
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, "data", "backtest.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(clean({"weights": cal["weights"], "adopted": cal["adopted"], "date": out["date"],
                     "test_excess_base": cal["test_excess_base"], "test_excess_blend": cal["test_excess_blend"]}),
              open(os.path.join(ROOT, "data", "weights.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"backtest done in {out['runtime_min']:.1f} min: base {out['base']['stats']}")
    return out
