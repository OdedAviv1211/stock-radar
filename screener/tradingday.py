"""לוח ימי המסחר בארה"ב – בלי תלות בספריות חיצוניות.

נותן שורה כמו "נתוני מסחר מ-6.11.2026 (יום ו׳) · סוף שבוע – אין מסחר" לדוח ולהודעת הטלגרם,
ומסמן כשהנתונים ישנים יותר ממה שמצופה (חסר יום מסחר)."""
from datetime import date, datetime, timedelta, timezone

# חגים שבהם NYSE סגורה (ימי חול בלבד; חג שחל בסוף שבוע כבר מופיע בתאריך שבו הוא נצפה בפועל).
HOLIDAYS = {
    "2026-01-01": "ראש השנה האזרחית", "2026-01-19": "יום מרטין לותר קינג", "2026-02-16": "יום הנשיאים",
    "2026-04-03": "יום שישי הטוב", "2026-05-25": "יום הזיכרון האמריקאי", "2026-06-19": "Juneteenth",
    "2026-07-03": "יום העצמאות האמריקאי (נצפה)", "2026-09-07": "יום העבודה האמריקאי", "2026-11-26": "חג ההודיה",
    "2026-12-25": "חג המולד",
    "2027-01-01": "ראש השנה האזרחית", "2027-01-18": "יום מרטין לותר קינג", "2027-02-15": "יום הנשיאים",
    "2027-03-26": "יום שישי הטוב", "2027-05-31": "יום הזיכרון האמריקאי", "2027-06-18": "Juneteenth (נצפה)",
    "2027-07-05": "יום העצמאות האמריקאי (נצפה)", "2027-09-06": "יום העבודה האמריקאי", "2027-11-25": "חג ההודיה",
    "2027-12-24": "חג המולד (נצפה)",
}
CLOSE_UTC = 21        # סגירת וול סטריט בשעון חורף (21:00 UTC); בקיץ 20:00 – ההערכה שמרנית
DAY = ["ב׳", "ג׳", "ד׳", "ה׳", "ו׳", "שבת", "א׳"]


def is_trading_day(d):
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def last_session(now_utc):
    """יום המסחר האחרון שהסגירה שלו כבר פורסמה."""
    d = now_utc.date()
    if now_utc.hour < CLOSE_UTC:
        d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def fmt(d):
    return f"{d.day}.{d.month}.{d.year} (יום {DAY[d.weekday()]})"


def closed_reason(days):
    """תיאור קצר של ימים ללא מסחר: סוף שבוע ו/או חג."""
    out = []
    if any(d.weekday() >= 5 for d in days):
        out.append("סוף שבוע – אין מסחר")
    for d in days:
        h = HOLIDAYS.get(d.isoformat())
        if h and d.weekday() < 5:
            out.append(f"{h} ({d.day}.{d.month}) – הבורסה בארה\"ב סגורה")
    return " · ".join(dict.fromkeys(out))


def note(asof, now_utc=None):
    """(שורה בעברית, סטטוס). סטטוס: fresh – הנתונים מיום המסחר האחרון; stale – חסר לפחות יום מסחר אחד."""
    now_utc = now_utc or datetime.now(timezone.utc)
    a = date.fromisoformat(str(asof)[:10])
    exp = last_session(now_utc)
    txt = f"נתוני מסחר מ-{fmt(a)}"
    if a >= exp:
        gap = [a + timedelta(days=i) for i in range(1, (now_utc.date() - a).days + 1)]
        reason = closed_reason([d for d in gap if not is_trading_day(d)])
        return (f"{txt} · {reason}" if reason else txt), "fresh"
    missing = [a + timedelta(days=i) for i in range(1, (exp - a).days + 1)]
    missing = [d for d in missing if is_trading_day(d)]
    return f"{txt} · ⚠️ חסרים נתונים של {len(missing)} ימי מסחר (אחרון צפוי {fmt(exp)})", "stale"


if __name__ == "__main__":
    for s, now in [("2026-11-06", "2026-11-07T08:50"), ("2026-11-06", "2026-11-09T09:50"), ("2026-11-06", "2026-11-10T02:20"),
                   ("2026-11-09", "2026-11-09T22:30"), ("2026-11-25", "2026-11-27T09:00"), ("2026-11-25", "2026-11-28T09:00")]:
        print(s, now, "→", note(s, datetime.fromisoformat(now).replace(tzinfo=timezone.utc)))
