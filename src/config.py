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
BACKTEST_COMMISSION_BUY = 0.00035
BACKTEST_COMMISSION_SELL = 0.00035
BACKTEST_SLIPPAGE = 0.001  # 0.1% slippage per trade (realistic for mid/large cap)
BACKTEST_MAX_POSITION_CAP = 3.0  # max position = initial_capital * max_per_position * cap
BACKTEST_HOLD_DAYS_AFTER = 1
BACKTEST_BUY_DAYS_BEFORE = 1

CALC_MIN_QUARTERS = 4
