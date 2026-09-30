"""זיהוי תבניות גרף קלאסיות (William O'Neil / IBD):
כוס וידית, בסיס שטוח, תחתית כפולה (W), דגל גבוה וצר.
הכללים פשוטים ושמרניים – זיהוי אוטומטי אינו מחליף מבט בגרף."""
import numpy as np


def _cup_handle(h, l, c, v):
    n = len(c)
    if n < 80:
        return None
    lo_i = max(0, n - 200)
    hi_i = n - 35
    if hi_i <= lo_i:
        return None
    L = lo_i + int(np.argmax(h[lo_i:hi_i]))
    lip = h[L]
    B = L + int(np.argmin(l[L:]))
    if B - L < 10 or n - B < 10:
        return None
    depth = 1 - l[B] / lip
    if not 0.12 <= depth <= 0.40:
        return None
    R = B + int(np.argmax(h[B:]))
    if h[R] < 0.90 * lip or R - B < 10 or R - L < 30:
        return None
    nh = n - 1 - R
    if not 4 <= nh <= 25:
        return None
    hlow = l[R:].min()
    if 1 - hlow / h[R] > 0.12 or hlow < (lip + l[B]) / 2:
        return None
    if v[R:].mean() > v[-50:].mean() * 1.05:
        return None
    price = c[-1]
    if price > h[R] * 1.03 or price < hlow:
        return None
    return {"name": "כוס וידית", "pivot": float(h[R]), "target": float(h[R] + (lip - l[B])),
            "detail": f"עומק כוס {depth * 100:.0f}%, ידית {nh} ימים בנפח נמוך"}


def _flat_base(h, l, c):
    n = len(c)
    best = None
    for k in range(25, 66, 5):
        if n < k + 70:
            break
        top, bot = h[-k:].max(), l[-k:].min()
        if (top - bot) / top <= 0.15:
            prior = c[-k] / l[-k - 60:-k].min()
            if prior >= 1.20:
                best = (k, top, (top - bot) / top)
    if not best:
        return None
    k, top, rng = best
    return {"name": "בסיס שטוח", "pivot": float(top), "target": float(top * (1 + rng)), "detail": f"{k} ימים בטווח {rng * 100:.0f}% אחרי עלייה"}


def _double_bottom(h, l, c):
    n = len(c)
    if n < 100:
        return None
    w = l[-150:]
    off = n - len(w)
    mins = [i for i in range(5, len(w) - 3) if w[i] == w[max(0, i - 5):i + 6].min()]
    if len(mins) < 2:
        return None
    A = min(mins, key=lambda i: w[i])
    for Bi in sorted(mins, key=lambda i: w[i])[1:]:
        if abs(Bi - A) < 15 or abs(w[Bi] / w[A] - 1) > 0.05:
            continue
        a, b = sorted((A, Bi))
        mid = a + int(np.argmax(h[off + a:off + b])) if b > a else a
        M = h[off + mid]
        if M < 1.10 * max(w[a], w[b]) or len(w) - b > 60:
            continue
        price = c[-1]
        if price < w[b] or price > M * 1.03:
            continue
        return {"name": "תחתית כפולה (W)", "pivot": float(M), "target": float(M + (M - min(w[a], w[b]))),
                "detail": f"שתי תחתיות בהפרש {abs(w[b] / w[a] - 1) * 100:.0f}%, {b - a} ימים ביניהן"}
    return None


def _high_tight_flag(h, l, c):
    n = len(c)
    for k in range(10, 26):
        if n < k + 45:
            break
        run = c[-k] / l[-k - 40:-k].min()
        if run >= 1.9:
            top = h[-k:].max()
            if (top - l[-k:].min()) / top <= 0.25:
                return {"name": "דגל גבוה וצר", "pivot": float(top), "target": float(top * 1.25),
                        "detail": f"עלייה של {(run - 1) * 100:.0f}% ואז דשדוש צר"}
    return None


def detect(df):
    """מחזיר רשימת תבניות שזוהו בסוף הגרף."""
    df = df.dropna(subset=["Close"]).iloc[-260:]
    if len(df) < 80:
        return []
    c = df["Close"].values.astype(float)
    h = df["High"].fillna(df["Close"]).values.astype(float)
    l = df["Low"].fillna(df["Close"]).values.astype(float)
    v = df["Volume"].fillna(0).values.astype(float)
    out = []
    for fn, args in ((_cup_handle, (h, l, c, v)), (_flat_base, (h, l, c)), (_double_bottom, (h, l, c)),
                     (_high_tight_flag, (h, l, c))):
        try:
            p = fn(*args)
        except Exception:  # noqa
            p = None
        if p:
            p["dist"] = float(c[-1] / p["pivot"] - 1)
            out.append(p)
    return out
