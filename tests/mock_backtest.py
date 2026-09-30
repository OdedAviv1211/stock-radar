"""בדיקה לאחור על נתונים סינתטיים: python -m tests.mock_backtest"""
import tests.mock_run  # noqa: F401 – מחליף את הורדת הנתונים בנתונים סינתטיים
from screener import backtest, config

config.BT_TRIALS = 60
if __name__ == "__main__":
    out = backtest.run()
    print(out["base"]["stats"])
    print(out["calibrated"]["stats"])
    print(out["calibration"])
    print(out["ic"])
