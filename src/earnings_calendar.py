"""Earnings calendar: yfinance primary, Nasdaq fallback, local cache"""
import pandas as pd
import requests
import json
import time
import os
from datetime import datetime, timedelta
from tqdm import tqdm
from bs4 import BeautifulSoup
from src.config import DATA_RAW

CACHE_PATH = f"{DATA_RAW}/earnings_cache.csv"

def _get_actual_dates_yfinance(ticker: str) -> list[dict]:
    """Get actual (historical) earnings dates from yfinance"""
    import yfinance as yf
    results = []
    try:
        tk = yf.Ticker(ticker)
        ed = tk.earnings_dates
        if ed is None or ed.empty:
            return results
        ed_actual = ed.dropna(subset=["Reported EPS"])
        for idx, row in ed_actual.iterrows():
            if pd.isna(idx):
                continue
            dt = idx.to_pydatetime() if hasattr(idx, 'to_pydatetime') else idx
            surprise = row.get("Surprise(%)", None)
            results.append({
                "ticker": ticker,
                "date": dt.date() if hasattr(dt, 'date') else dt,
                "datetime": dt,
                "surprise_pct": surprise if pd.notna(surprise) else None,
                "source": "yfinance",
            })
    except Exception:
        pass
    return results

def _get_dates_nasdaq_fallback(ticker: str) -> list[dict]:
    """Fallback: scrape Nasdaqs latest earnings date"""
    results = []
    try:
        url = f"https://www.nasdaq.com/market-activity/stocks/{ticker.lower()}/earnings"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells) >= 1:
                    date_str = cells[0].get_text(strip=True)
                    if date_str:
                        try:
                            dt = datetime.strptime(date_str, "%m/%d/%Y")
                            results.append({
                                "ticker": ticker,
                                "date": dt.date(),
                                "datetime": dt,
                                "surprise_pct": None,
                                "source": "nasdaq",
                            })
                        except ValueError:
                            pass
        if results:
            return results[:20]
    except Exception:
        pass
    return results

def get_earnings_dates(tickers: list[str], force_refresh: bool = False) -> pd.DataFrame:
    """Get actual historical earnings dates for a list of tickers"""
    if os.path.exists(CACHE_PATH) and not force_refresh:
        df_cache = pd.read_csv(CACHE_PATH)
        cached_tickers = set(df_cache["ticker"].unique())
        need = [t for t in tickers if t not in cached_tickers]
        if not need:
            return df_cache[df_cache["ticker"].isin(tickers)]
    else:
        need = tickers
        df_cache = pd.DataFrame()

    print(f"Fetching earnings dates for {len(need)} tickers...")
    all_dates = []
    for t in tqdm(need, desc="Earnings"):
        dates = _get_actual_dates_yfinance(t)
        if not dates:
            dates = _get_dates_nasdaq_fallback(t)
        all_dates.extend(dates)
        time.sleep(0.05)

    df_new = pd.DataFrame(all_dates)
    if not df_cache.empty and not df_new.empty:
        df_all = pd.concat([df_cache, df_new], ignore_index=True).drop_duplicates(
            subset=["ticker", "date"]
        )
    elif not df_new.empty:
        df_all = df_new
    else:
        df_all = df_cache

    if not df_all.empty:
        df_all.to_csv(CACHE_PATH, index=False)
        print(f"  Cached {len(df_all)} earnings dates -> {CACHE_PATH}")

    return df_all[df_all["ticker"].isin(tickers)]

def get_earnings_bounds(earnings_date, earnings_datetime=None) -> tuple:
    """Determine buy and sell dates, shifted to nearest NYSE trading days.

    Returns (buy_date, sell_date) as date objects.
    """
    if isinstance(earnings_date, str):
        earnings_date = datetime.strptime(earnings_date[:10], "%Y-%m-%d").date()

    if earnings_datetime is not None:
        hour = earnings_datetime.hour if hasattr(earnings_datetime, 'hour') else 0
        if hour >= 16:
            buy_date = earnings_date
        else:
            buy_date = prev_trading_day(earnings_date)
    else:
        buy_date = prev_trading_day(earnings_date)

    sell_date = next_trading_day(earnings_date)
    return buy_date, sell_date


# === Trading calendar helpers ===

class _TradingCalendar:
    """NYSE trading calendar: weekends + major holidays"""
    def __init__(self):
        self._holidays = self._build_holidays(2000, 2030)

    @staticmethod
    def _build_holidays(from_year: int, to_year: int) -> set:
        """Generate set of NYSE holiday dates"""
        holidays = set()
        for y in range(from_year, to_year + 1):
            # New Year's Day
            holidays.update(_observed(Date(y, 1, 1)))
            # MLK Day (3rd Monday of January)
            holidays.add(_nth_weekday(y, 1, 0, 3))
            # Presidents' Day (3rd Monday of February)
            holidays.add(_nth_weekday(y, 2, 0, 3))
            # Good Friday (approximate: Friday before Easter)
            # Easter approximation (calendar based)
            a = y % 19; b = y // 100; c = y % 100
            d = b // 4; e = b % 4; f = (b + 8) // 25
            g = (b - f + 1) // 3; h = (19 * a + b - d - g + 15) % 30
            i = c // 4; k = c % 4; l = (32 + 2 * e + 2 * i - h - k) % 7
            m = (a + 11 * h + 22 * l) // 451
            month = (h + l - 7 * m + 114) // 31
            day = ((h + l - 7 * m + 114) % 31) + 1
            easter = Date(y, month, day)
            holidays.add(easter - timedelta(days=2))  # Good Friday
            # Memorial Day (last Monday of May)
            last_may = Date(y, 5, 31)
            while last_may.weekday() != 0:
                last_may -= timedelta(days=1)
            holidays.add(last_may)
            # Juneteenth (June 19)
            holidays.update(_observed(Date(y, 6, 19)))
            # Independence Day
            holidays.update(_observed(Date(y, 7, 4)))
            # Labor Day (1st Monday of September)
            holidays.add(_nth_weekday(y, 9, 0, 1))
            # Thanksgiving (4th Thursday of November)
            holidays.add(_nth_weekday(y, 11, 3, 4))
            # Christmas
            holidays.update(_observed(Date(y, 12, 25)))
        return holidays

    def is_trading_day(self, d) -> bool:
        """Check if date is a NYSE trading day"""
        if isinstance(d, datetime):
            d = d.date()
        if d.weekday() >= 5:  # Saturday/Sunday
            return False
        if d in self._holidays:
            return False
        return True

Date = lambda y, m, d: datetime(y, m, d).date()

def _observed(d):
    """Return set of dates: actual holiday + observed (if on weekend)"""
    result = {d}
    if d.weekday() == 5:  # Saturday → observed Friday
        result.add(d - timedelta(days=1))
    elif d.weekday() == 6:  # Sunday → observed Monday
        result.add(d + timedelta(days=1))
    return result

def _nth_weekday(year, month, weekday, n):
    """Return nth weekday of month (e.g. 3rd Monday)"""
    first = Date(year, month, 1)
    days_until = (weekday - first.weekday()) % 7
    return first + timedelta(days=days_until + (n - 1) * 7)

_cal = _TradingCalendar()

def prev_trading_day(d):
    """Return previous NYSE trading day (≤ d, never forward)"""
    if isinstance(d, datetime):
        d = d.date()
    while not _cal.is_trading_day(d):
        d -= timedelta(days=1)
    return d

def next_trading_day(d):
    """Return next NYSE trading day (strictly > d)"""
    if isinstance(d, datetime):
        d = d.date()
    d += timedelta(days=1)
    while not _cal.is_trading_day(d):
        d += timedelta(days=1)
    return d

if __name__ == "__main__":
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
    df = get_earnings_dates(tickers, force_refresh=True)
    for _, row in df.head(10).iterrows():
        print(f"  {row['ticker']}: {row['date']} (surprise={row['surprise_pct']}%)")
