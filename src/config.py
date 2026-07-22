import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_RAW = os.path.join(BASE_DIR, "data", "raw")
DATA_PROCESSED = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

for d in [DATA_RAW, DATA_PROCESSED, OUTPUT_DIR]:
    os.makedirs(d, exist_ok=True)

SCREENER_MIN_MARKET_CAP = 500_000_000
SCREENER_EXCLUDE_SECTORS = [
    "Financial Services",
    "Insurance",
    "Banks",
    "Diversified Financials",
    "Capital Markets",
]
SCREENER_EXCLUDE_TYPES = ["ETF", "SPAC", "REIT", "Closed-End Fund"]

FILTER_K_THRESHOLD = 1.1
FILTER_MIN_QUARTERS_ABOVE = 2
FILTER_MIN_LOOKBACK_QUARTERS = 2
FILTER_MIN_VOLUME = 100_000
FILTER_EXCLUDE_SECTORS = ["Financial Services", "Insurance", "Banks", "Capital Markets",
                          "Consumer Defensive", "Utilities", "Real Estate", "Energy", "Healthcare"]

BACKTEST_MAX_DEPOSIT_PER_POSITION = 0.33
BACKTEST_MAX_CONCURRENT_POSITIONS = 3
BACKTEST_MAX_POS_FRAC = 0.50  # hard cap: не больше 50% капитала на сделку
BACKTEST_STOP_LOSS = -0.05    # -5% stop-loss (выход по Low дня)
BACKTEST_COMMISSION_BUY = 0.00035
BACKTEST_COMMISSION_SELL = 0.00035
BACKTEST_SLIPPAGE = 0.001  # 0.1% slippage per trade
BACKTEST_HOLD_DAYS_AFTER = 1
BACKTEST_BUY_DAYS_BEFORE = 1

CALC_MIN_QUARTERS = 4

# Email notifications (mail.ru)
# Пароль читается из .env или переменной окружения
def _load_env():
    env_file = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

_load_env()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.mail.ru")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "mirus3000@mail.ru")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "mirus3000@mail.ru")
