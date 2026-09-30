"""חישוב אינדיקטורים טכניים לכל מניה.
תאוריות: ממוצע 150 (Weinstein Stage Analysis), Trend Template (Minervini), RS Rating (IBD/O'Neil),
VCP – התכווצות תנודתיות (Minervini), פיבוט ופריצה בנפח (O'Neil/Darvas), איסוף מוסדי (Up/Down Volume),
RSI ו-MACD."""
import numpy as np
import pandas as pd

MIN_BARS = 230

# מאפיינים המשמשים להשוואה למניות שהתפוצצו בעבר (רק מחיר/נפח – כדי שיהיה אפשר לחשב גם לתאריכי עבר)
ANALOG_FEATURES = ["ex_ret_3m", "ex_ret_6m", "dist_hi", "ext_sma150", "sma150_slope", "sma50_vs_150",
                   "vol_contract", "updown", "vol_surge", "above_lo", "atr_pct"]


def _ret(c, n):
    return float(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n and c.iloc[-1 - n] > 0 else np.nan


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return float((100 - 100 / (1 + rs)).iloc[-1])


def compute(df, bench_close=None, with_series=False):
    """df: עמודות Open/High/Low/Close/Volume, אינדקס תאריכים. מחזיר dict או None."""
    df = df.dropna(subset=["Close"])
    if len(df) < MIN_BARS:
        return None
    c, h, l, v = df["Close"], df["High"].fillna(df["Close"]), df["Low"].fillna(df["Close"]), df["Volume"].fillna(0)
    price = float(c.iloc[-1])
    if price <= 0:
        return None
    s50, s150, s200 = c.rolling(50).mean(), c.rolling(150).mean(), c.rolling(200).mean()
    sma50, sma150, sma200 = float(s50.iloc[-1]), float(s150.iloc[-1]), float(s200.iloc[-1])
    sma150_slope = float(s150.iloc[-1] / s150.iloc[-21] - 1)
    sma200_slope = float(s200.iloc[-1] / s200.iloc[-22] - 1) if not np.isnan(s200.iloc[-22]) else np.nan
    win = min(252, len(df))
    hi52, lo52 = float(h.iloc[-win:].max()), float(l.iloc[-win:].min())

    r = {n: _ret(c, d) for n, d in (("r1d", 1), ("r5d", 5), ("r21", 21), ("r63", 63), ("r126", 126), ("r189", 189), ("r252", 252))}
    parts = [(0.4, r["r63"]), (0.2, r["r126"]), (0.2, r["r189"]), (0.2, r["r252"])]
    parts = [(w, x) for w, x in parts if not np.isnan(x)]
    rs_raw = sum(w * x for w, x in parts) / sum(w for w, _ in parts) if parts else np.nan

    b3 = b6 = 0.0
    if bench_close is not None:
        bc = bench_close.reindex(c.index).ffill().dropna()
        if len(bc) > 130:
            b3, b6 = _ret(bc, 63), _ret(bc, 126)
    ex3 = (1 + r["r63"]) / (1 + b3) - 1
    ex6 = (1 + r["r126"]) / (1 + b6) - 1

    rets = c.pct_change()
    std10, std60 = rets.iloc[-10:].std(), rets.iloc[-60:].std()
    vol_contract = float(std10 / std60) if std60 and std60 > 0 else 1.0
    last50 = df.iloc[-50:]
    ch = last50["Close"].diff()
    upv, dnv = float(last50["Volume"][ch > 0].sum()), float(last50["Volume"][ch < 0].sum())
    updown = upv / dnv if dnv > 0 else 2.0
    vol20, vol50, vol100 = float(v.iloc[-20:].mean()), float(v.iloc[-50:].mean()), float(v.iloc[-100:].mean())
    vol_surge = vol20 / vol100 if vol100 > 0 else 1.0
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr_pct = float(tr.iloc[-20:].mean() / price)
    tight10 = float((h.iloc[-10:].max() - l.iloc[-10:].min()) / price)
    pivot = float(h.iloc[-61:-1].max())
    dist_pivot = price / pivot - 1
    breakout = bool(price > pivot and v.iloc[-1] > 1.4 * vol50)
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_hist = float((macd - macd.ewm(span=9, adjust=False).mean()).iloc[-1])

    # Weinstein stage (ממוצע 150 יום ≈ ממוצע 30 שבועות)
    flat = abs(sma150_slope) < 0.01
    if price > sma150 and sma150_slope > 0:
        stage = 2
    elif price < sma150 and sma150_slope < 0:
        stage = 4
    elif flat and price < sma150 * 1.05:
        stage = 1
    else:
        stage = 3 if price < sma150 or flat else 2

    tt = [  # Minervini Trend Template (7 מתוך 8; ה-RS מתווסף בשלב הניקוד)
        price > sma150 and price > sma200,
        sma150 > sma200,
        (sma200_slope > 0) if not np.isnan(sma200_slope) else False,
        sma50 > sma150 and sma50 > sma200,
        price > sma50,
        price >= 1.3 * lo52,
        price >= 0.75 * hi52,
    ]

    f = {
        "price": price, "sma50": sma50, "sma150": sma150, "sma200": sma200,
        "sma150_slope": sma150_slope, "sma200_slope": sma200_slope,
        "ext_sma150": price / sma150 - 1, "ext_sma50": price / sma50 - 1, "sma50_vs_150": sma50 / sma150 - 1,
        "hi52": hi52, "lo52": lo52, "dist_hi": price / hi52 - 1, "above_lo": price / lo52 - 1,
        **r, "rs_raw": rs_raw, "ex_ret_3m": ex3, "ex_ret_6m": ex6,
        "vol_contract": vol_contract, "updown": updown, "vol_surge": vol_surge, "atr_pct": atr_pct,
        "tight10": tight10, "pivot": pivot, "dist_pivot": dist_pivot, "breakout": breakout,
        "rsi": rsi(c), "macd_hist": macd_hist, "stage": stage, "tt": tt, "tt_count": int(sum(tt)),
        "dollar_vol": float((c.iloc[-20:] * v.iloc[-20:]).mean()),
        "low10": float(l.iloc[-10:].min()), "new_high": price >= 0.98 * hi52,
        "above150": price > sma150, "above50": price > sma50,
        "bars": len(df), "last_date": str(df.index[-1].date()),
    }
    if with_series:
        n = min(252, len(df))
        f["series"] = {
            "d": [str(x.date()) for x in df.index[-n:]],
            "c": [round(float(x), 4) for x in c.iloc[-n:]],
            "s50": [None if np.isnan(x) else round(float(x), 4) for x in s50.iloc[-n:]],
            "s150": [None if np.isnan(x) else round(float(x), 4) for x in s150.iloc[-n:]],
            "s200": [None if np.isnan(x) else round(float(x), 4) for x in s200.iloc[-n:]],
        }
    return f
