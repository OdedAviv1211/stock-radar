"""הורדת נתונים: רשימת מניות ארה"ב (Nasdaq screener), מניות ת"א, היסטוריית מחירים ונתונים פונדמנטליים (Yahoo)."""
import json
import os
import re
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

from . import config

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json, text/plain, */*"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUDE_NAME = re.compile(r"\b(Warrants?|Rights?|Units?|Preferred|Notes due|Debentures|Subordinated)\b", re.I)


def log(msg):
    print(f"[{datetime.utcnow():%H:%M:%S}] {msg}", flush=True)


def _num(s):
    if s in (None, "", "NA", "N/A"):
        return None
    try:
        return float(str(s).replace("$", "").replace(",", "").replace("%", ""))
    except ValueError:
        return None


def us_universe():
    """רשימת כל המניות בארה"ב עם שווי שוק, סקטור ותעשייה."""
    url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25000&download=true"
    rows = []
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            r.raise_for_status()
            rows = r.json()["data"]["rows"]
            break
        except Exception as e:  # noqa
            log(f"nasdaq screener attempt {attempt + 1} failed: {e}")
            time.sleep(5)
    out = []
    if rows:
        for x in rows:
            sym = (x.get("symbol") or "").strip()
            name = x.get("name") or ""
            if not sym or "^" in sym or EXCLUDE_NAME.search(name):
                continue
            mcap, price = _num(x.get("marketCap")), _num(x.get("lastsale"))
            if not mcap or mcap < config.US_MIN_MARKET_CAP or not price or price < config.US_MIN_PRICE:
                continue
            out.append({"ticker": sym.replace("/", "-"), "name": name.split(" Common Stock")[0].split(" Class ")[0],
                        "mcap": mcap, "sector": x.get("sector") or "", "industry": x.get("industry") or "",
                        "market": "US"})
        log(f"US universe from nasdaq: {len(out)}")
        return out
    # גיבוי: רשימות nasdaqtrader (בלי שווי שוק – יסונן לפי מחזור אחר כך)
    log("falling back to nasdaqtrader symbol lists")
    for fn in ("nasdaqlisted.txt", "otherlisted.txt"):
        try:
            txt = requests.get(f"https://www.nasdaqtrader.com/dynamic/SymDir/{fn}", headers=UA, timeout=60).text
        except Exception as e:  # noqa
            log(f"{fn} failed: {e}")
            continue
        lines = txt.strip().splitlines()
        hdr = lines[0].split("|")
        for ln in lines[1:-1]:
            d = dict(zip(hdr, ln.split("|")))
            sym = d.get("Symbol") or d.get("ACT Symbol") or ""
            name = d.get("Security Name", "")
            if d.get("ETF") == "Y" or d.get("Test Issue") == "Y" or "$" in sym or "." in sym or EXCLUDE_NAME.search(name):
                continue
            out.append({"ticker": sym, "name": name.split(" - ")[0], "mcap": None, "sector": "", "industry": "",
                        "market": "US"})
    log(f"US universe fallback: {len(out)}")
    return out


def tase_universe():
    path = os.path.join(ROOT, "tase_tickers.txt")
    out = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.split("#")[0].strip()
            if not ln:
                continue
            parts = [p.strip() for p in ln.split(",")]
            out.append({"ticker": parts[0], "name": parts[1] if len(parts) > 1 else parts[0], "mcap": None,
                        "sector": parts[2] if len(parts) > 2 else "", "industry": "", "market": "TASE"})
    return out


def _split(df, tickers):
    res = {}
    if df is None or df.empty:
        return res
    if isinstance(df.columns, pd.MultiIndex):
        lvl0 = set(df.columns.get_level_values(0))
        for t in tickers:
            if t in lvl0:
                sub = df[t].dropna(how="all")
                if len(sub):
                    res[t] = sub
        if not res:  # מבנה עמודות הפוך (Price, Ticker)
            lvl1 = set(df.columns.get_level_values(1))
            for t in tickers:
                if t in lvl1:
                    sub = df.xs(t, axis=1, level=1).dropna(how="all")
                    if len(sub):
                        res[t] = sub
    elif len(tickers) == 1:
        res[tickers[0]] = df.dropna(how="all")
    return res


def download_history(tickers, period=config.HISTORY_PERIOD, start=None):
    import yfinance as yf
    out = {}
    tickers = list(dict.fromkeys(tickers))
    for i in range(0, len(tickers), config.DOWNLOAD_CHUNK):
        chunk = tickers[i:i + config.DOWNLOAD_CHUNK]
        df = None
        for attempt in range(4):
            try:
                kw = dict(interval="1d", auto_adjust=True, group_by="ticker", threads=True, progress=False)
                df = yf.download(chunk, start=start, **kw) if start else yf.download(chunk, period=period, **kw)
                break
            except Exception as e:  # noqa
                log(f"download chunk {i} attempt {attempt + 1} failed: {e}")
                time.sleep(15 * (attempt + 1))
        got = _split(df, chunk)
        for t, sub in got.items():
            sub = sub.rename(columns=str.title)
            if "Close" in sub and sub["Close"].notna().sum() > 0:
                out[t] = sub[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        log(f"history {i + len(chunk)}/{len(tickers)} (ok so far: {len(out)})")
        time.sleep(1.5)
    return out


FUND_KEYS = ["longName", "shortName", "sector", "industry", "marketCap", "revenueGrowth", "earningsGrowth",
             "earningsQuarterlyGrowth", "grossMargins", "operatingMargins", "returnOnEquity",
             "trailingAnnualDividendYield", "dividendYield", "forwardPE", "trailingPE", "trailingPegRatio",
             "heldPercentInstitutions", "shortPercentOfFloat", "targetMeanPrice", "recommendationMean",
             "numberOfAnalystOpinions", "currency", "financialCurrency",
             "earningsTimestamp", "earningsTimestampStart", "earningsTimestampEnd", "isEarningsDateEstimate"]


def fundamentals(tickers, max_age_days=5):
    """נתונים פונדמנטליים עם מטמון מקומי (כדי לא להעמיס על Yahoo)."""
    import yfinance as yf
    path = os.path.join(ROOT, "data", "fund_cache.json")
    cache = {}
    if os.path.exists(path):
        try:
            cache = json.load(open(path, encoding="utf-8"))
        except Exception:  # noqa
            cache = {}
    cutoff = (datetime.utcnow() - timedelta(days=max_age_days)).isoformat()
    out = {}
    empty_run, blocked = 0, False
    for n, t in enumerate(tickers):
        c = cache.get(t)
        if c and c.get("_ts", "") > cutoff:
            out[t] = c
            continue
        info = None
        if not blocked:
            for attempt in range(2):
                try:
                    raw = yf.Ticker(t).info or {}
                    info = {k: raw.get(k) for k in FUND_KEYS}
                    break
                except Exception as e:  # noqa
                    log(f"info {t} attempt {attempt + 1}: {e}")
                    time.sleep(3)
            # Yahoo לפעמים חוסם את שרתי GitHub (401 Invalid Crumb) ומחזיר תשובה ריקה – לא שומרים ריק במטמון
            if info is not None and all(v is None for v in info.values()):
                info = None
            empty_run = 0 if info else empty_run + 1
            if empty_run >= 8:
                blocked = True
                log("Yahoo fundamentals blocked from this server – fund score neutral, earnings dates from Nasdaq")
        if info is not None:
            info["_ts"] = datetime.utcnow().isoformat()
            cache[t] = info
            out[t] = info
        elif c:
            out[t] = c
        if n % 20 == 0:
            log(f"fundamentals {n}/{len(tickers)}")
        if not blocked:
            time.sleep(0.4)
    try:
        cal = nasdaq_earnings(days=21)
        for t in tickers:
            if t in cal and not (out.get(t) or {}).get("earningsTimestamp"):
                out.setdefault(t, {})["earningsTimestamp"] = cal[t]
        log(f"earnings calendar (Nasdaq): {len(cal)} upcoming reports")
    except Exception as e:  # noqa
        log(f"earnings calendar failed: {e}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(cache, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return out


def nasdaq_earnings(days=21):
    """לוח דוחות רבעוניים מ-Nasdaq: {טיקר: timestamp של יום הדוח}."""
    out = {}
    d0 = datetime.utcnow().date()
    for i in range(days):
        d = d0 + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            r = requests.get("https://api.nasdaq.com/api/calendar/earnings", params={"date": d.isoformat()},
                             headers=UA, timeout=20)
            rows = ((r.json().get("data") or {}).get("rows")) or []
        except Exception:  # noqa
            continue
        ts = datetime(d.year, d.month, d.day, 13).timestamp()
        for row in rows:
            sym = (row.get("symbol") or "").strip().upper()
            if sym and sym not in out:
                out[sym] = ts
        time.sleep(0.3)
    return out


def tase_market_caps(tickers):
    import yfinance as yf
    res = {}
    for t in tickers:
        try:
            fi = yf.Ticker(t).fast_info
            res[t] = (getattr(fi, "market_cap", None), getattr(fi, "currency", None))
        except Exception:  # noqa
            pass
        time.sleep(0.2)
    return res


def load_portfolio():
    """portfolio.csv: ticker,buy_price,buy_date,shares,stop,notes (רק ticker ו-buy_price חובה)."""
    import csv
    path = os.path.join(ROOT, "portfolio.csv")
    out = []
    if not os.path.exists(path):
        return out
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        t = (r.get("ticker") or "").strip().upper()
        if not t or t.startswith("#"):
            continue
        t = t.replace(".TA", ".TA")
        out.append({"ticker": t, "buy_price": _num(r.get("buy_price")), "buy_date": (r.get("buy_date") or "").strip(),
                    "shares": _num(r.get("shares")), "stop": _num(r.get("stop")), "notes": (r.get("notes") or "").strip()})
    return out
