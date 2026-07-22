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
    """Determine buy and sell dates based on earnings time.

    Returns (buy_date, sell_date) as date objects.
    If earnings is before market (BMO = before open), buy previous day close.
    If earnings is after market (AMC = after close), buy same day close.
    Sell at open next day after the earnings date.
    """
    if isinstance(earnings_date, str):
        earnings_date = datetime.strptime(earnings_date[:10], "%Y-%m-%d").date()

    if earnings_datetime is not None:
        hour = earnings_datetime.hour if hasattr(earnings_datetime, 'hour') else 0
        if hour >= 16:  # After market close (4 PM+)
            buy_date = earnings_date
        else:  # Before market open
            buy_date = earnings_date - timedelta(days=1)
    else:
        buy_date = earnings_date - timedelta(days=1)

    sell_date = earnings_date + timedelta(days=1)
    return buy_date, sell_date

if __name__ == "__main__":
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
    df = get_earnings_dates(tickers, force_refresh=True)
    for _, row in df.head(10).iterrows():
        print(f"  {row['ticker']}: {row['date']} (surprise={row['surprise_pct']}%)")
