"""השוואה למניות שהתפוצצו בעבר.
לכל "מנצחת היסטורית" מחושבת טביעת אצבע טכנית (אותם מדדים בדיוק) בתאריך שלפני הריצה הגדולה,
מנתוני אמת שמורדים בכל ריצה. אחר כך נמדד כמה כל מניה היום דומה לכל טביעת אצבע,
ומוצגת גם התשואה שהמנצחת עשתה בפועל ב-6 וב-12 החודשים שאחרי."""
import numpy as np
import pandas as pd

from .indicators import ANALOG_FEATURES, compute

# (טיקר, תאריך "לפני הפיצוץ", תיאור). התאריכים הם נקודות מבנה/פריצה לפני ריצות גדולות.
WINNERS = [
    ("NVDA", "2016-05-20", "אנבידיה 2016 – GPU לדאטה סנטר"),
    ("NVDA", "2023-01-24", "אנבידיה 2023 – גל ה-AI"),
    ("AMD", "2016-07-01", "AMD 2016 – תפנית"),
    ("SMCI", "2023-01-25", "סופרמיקרו 2023 – שרתי AI"),
    ("TSLA", "2019-11-01", "טסלה 2019"),
    ("ENPH", "2019-06-03", "אנפייז 2019 – סולארי"),
    ("CELH", "2020-06-01", "סלסיוס 2020"),
    ("META", "2023-01-27", "מטא 2023 – שנת היעילות"),
    ("AVGO", "2023-05-01", "ברודקום 2023"),
    ("ANET", "2023-05-02", "אריסטה 2023"),
    ("LLY", "2023-04-28", "אלי לילי 2023 – GLP-1"),
    ("APP", "2023-06-01", "אפלוביין 2023"),
    ("PLTR", "2024-09-03", "פלנטיר 2024"),
    ("VST", "2024-01-24", "ויסטרה 2024 – חשמל ל-AI"),
    ("CRWD", "2023-06-01", "קראודסטרייק 2023"),
    ("ELF", "2022-11-01", "e.l.f. 2022"),
    ("MSTR", "2024-09-10", "מיקרוסטרטג'י 2024"),
    ("SHOP", "2019-01-25", "שופיפיי 2019"),
]


def build_library(histories, bench_close):
    lib = []
    for t, date, label in WINNERS:
        df = histories.get(t)
        if df is None:
            continue
        past = df.loc[:date]
        if len(past) < 230:
            continue
        b = bench_close.loc[:date] if bench_close is not None else None
        f = compute(past, b)
        if not f:
            continue
        i = len(past) - 1
        c = df["Close"]
        fwd6 = float(c.iloc[min(i + 126, len(c) - 1)] / c.iloc[i] - 1)
        fwd12 = float(c.iloc[min(i + 252, len(c) - 1)] / c.iloc[i] - 1)
        lib.append({"ticker": t, "date": date, "label": label, "fwd6": fwd6, "fwd12": fwd12,
                    "vec": {k: f[k] for k in ANALOG_FEATURES}})
    return lib


def score_similarity(feats_by_ticker, lib):
    """מחזיר {ticker: (similarity 0-100, analog)} – סטנדרטיזציה חסינה לפי חתך השוק של היום."""
    if not lib or not feats_by_ticker:
        return {}
    tickers = list(feats_by_ticker)
    M = pd.DataFrame([{k: feats_by_ticker[t].get(k, np.nan) for k in ANALOG_FEATURES} for t in tickers], index=tickers)
    med = M.median()
    iqr = (M.quantile(0.75) - M.quantile(0.25)).replace(0, np.nan).fillna(1.0) / 1.35
    Z = ((M - med) / iqr).clip(-3, 3).fillna(0)
    L = pd.DataFrame([a["vec"] for a in lib])
    LZ = ((L - med) / iqr).clip(-3, 3).fillna(0).values
    res = {}
    for t, row in zip(tickers, Z.values):
        d = np.sqrt(((LZ - row) ** 2).sum(axis=1))
        j = int(np.argmin(d))
        sim = float(100 * np.exp(-(d[j] / 3.0) ** 2))
        res[t] = (sim, lib[j])
    return res
