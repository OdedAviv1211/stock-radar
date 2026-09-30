"""בדיקת קצה-לקצה עם נתונים סינתטיים (בלי אינטרנט). python -m tests.mock_run
הדוח שנוצר הוא לבדיקה בלבד – המספרים אינם אמיתיים."""
import random
import zlib
import time

import numpy as np
import pandas as pd

from screener import data, pipeline, themes

rng = np.random.default_rng(7)
random.seed(7)
DATES = pd.bdate_range("2014-01-02", "2026-09-28")
SECTORS = ["Technology", "Health Care", "Finance", "Energy", "Utilities", "Industrials", "Consumer Discretionary",
           "Consumer Staples", "Real Estate", "Basic Materials", "Telecommunications"]
IND = ["Semiconductors", "Software", "Banks", "Oil & Gas", "Biotech", "Aerospace", "Retail", "REIT", "Utilities",
       "Chemicals", "Internet", "Medical Devices", "Insurance", "Industrial Machinery", "Restaurants"]

named = sorted({t for ts in themes.AI_CHAIN.values() for t in ts if not t.endswith(".TA")} |
               {t for ts in themes.SPECIAL.values() for t in ts if not t.endswith(".TA")} | {"TSLA", "ENPH", "CELH", "LLY", "ELF", "SHOP", "JNJ", "XOM", "KO", "JPM"})
US = [{"ticker": t, "name": f"{t} Inc.", "mcap": float(10 ** rng.uniform(8.6, 12.4)), "sector": random.choice(SECTORS),
       "industry": random.choice(IND), "market": "US"} for t in named]
US += [{"ticker": f"X{i:03d}", "name": f"Synthetic {i}", "mcap": float(10 ** rng.uniform(8.5, 11.5)),
        "sector": random.choice(SECTORS), "industry": random.choice(IND), "market": "US"} for i in range(500)]

_cache = {}


def synth(t):
    if t in _cache:
        return _cache[t]
    rng = np.random.default_rng(zlib.crc32(t.encode()))  # דטרמיניסטי לכל טיקר
    n = len(DATES)
    drift = rng.normal(0.0003, 0.0007)
    vol = rng.uniform(0.012, 0.035)
    r = rng.normal(drift, vol, n)
    # רוב המניות: משטר מגמה בשנה האחרונה
    r[-260:] += rng.normal(0.0008, 0.0012)
    p = 50 * np.exp(np.cumsum(r))
    if t.endswith(".TA"):
        p *= 40
    hi = p * (1 + rng.uniform(0, vol, n))
    lo = p * (1 - rng.uniform(0, vol, n))
    v = rng.lognormal(13, .5, n) * (1 + (r > 0) * rng.uniform(0, .4))
    df = pd.DataFrame({"Open": p, "High": hi, "Low": lo, "Close": p, "Volume": v}, index=DATES)
    _cache[t] = df
    return df


def fake_download(tickers, period=None, start=None):
    out = {}
    for t in tickers:
        if t == "ILS=X":
            out[t] = pd.DataFrame({"Open": 3.7, "High": 3.7, "Low": 3.7, "Close": 3.7, "Volume": 0}, index=DATES)
            continue
        df = synth(t)
        out[t] = df if start else df.iloc[-504:]
    return out


def fake_fund(tickers, max_age_days=5):
    return {t: {"longName": f"{t} Corp", "revenueGrowth": float(rng.normal(.18, .2)),
                "earningsQuarterlyGrowth": float(rng.normal(.2, .4)), "grossMargins": float(rng.uniform(.2, .8)),
                "returnOnEquity": float(rng.normal(.18, .12)), "forwardPE": float(rng.uniform(10, 60)),
                "trailingAnnualDividendYield": float(max(0, rng.normal(.01, .02))), "targetMeanPrice": None,
                "shortPercentOfFloat": float(rng.uniform(0, .2)),
                "earningsTimestampStart": time.time() + float(rng.uniform(-20, 80)) * 86400} for t in tickers}


data.us_universe = lambda: US
data.download_history = fake_download
data.fundamentals = fake_fund
data.tase_market_caps = lambda ts: {t: (float(10 ** rng.uniform(11, 13.5)), "ILA") for t in ts}

if __name__ == "__main__":
    rep = pipeline.run()
    print("picks:", [(p["t"], round(p["score"]), p["theme"], p["cap"]) for p in rep["picks"]])
    print("israel:", [(p["t"], round(p["score"])) for p in rep["israel"]])
    print("themes:", len(rep["themes"]), "heat:", len(rep["heat"]), "table:", len(rep["table"]),
          "analogs:", len(rep["analogs"]))
    print(rep["picks"][0]["good"], rep["picks"][0]["warn"], rep["picks"][0]["plan"])
