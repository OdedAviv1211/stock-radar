"""python -m tests.mock_watch – בדיקת התראות המעקב על נתונים סינתטיים."""
import numpy as np
from tests.mock_run import synth
import watch_alerts
from screener import watch

hist = {r["ticker"]: synth(r["ticker"]).iloc[-400:].copy() for r in watch.load_watchlist()}
# תרחישים מכוונים: שבירת 150, קפיצה בנפח, תיקון ל-20
d = hist["ONDS"]; d.iloc[-1, d.columns.get_loc("Close")] = d["Close"].iloc[-150:].mean() * 0.97
d = hist["NVDA"]; d.iloc[-1, d.columns.get_loc("Close")] *= 1.07; d.iloc[-1, d.columns.get_loc("Volume")] *= 3
rows, alerts = watch_alerts.run(hist)
for r in rows:
    print(f"{r['t']:5} {r['sector']:12} {r.get('action', r.get('error'))} | " + "; ".join(e["text"] for e in r.get("events", [])))
print()
print(watch_alerts.message(alerts) if alerts else "no alerts")
rows2, alerts2 = watch_alerts.run(hist)
print("\nsecond run (dedupe) alerts:", len(alerts2))
