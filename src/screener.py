import requests
import yfinance as yf
import pandas as pd
from tqdm import tqdm
from io import StringIO
from src.config import SCREENER_MIN_MARKET_CAP, SCREENER_EXCLUDE_SECTORS

def get_all_tickers() -> list[str]:
    """Fetch all US tickers from NASDAQ/NYSE using yfinance"""
    sp500 = []
    try:
        resp = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        sp500 = pd.read_html(resp.text)[0]["Symbol"].tolist()
    except Exception:
        pass
    nasdaq = []
    try:
        resp = requests.get(
            "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        df = pd.read_csv(StringIO(resp.text), sep="|")
        nasdaq = df["Symbol"].dropna().tolist()
    except Exception:
        pass
    nyse = []
    try:
        resp = requests.get(
            "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        df = pd.read_csv(StringIO(resp.text), sep="|")
        nyse = df["ACT Symbol"].dropna().tolist()
    except Exception:
        pass
    all_tickers = list(set(sp500 + nasdaq + nyse))
    tickers_clean = [
        t.split(".")[0].strip() for t in all_tickers
        if isinstance(t, str) and not t.startswith("$")
    ]
    return tickers_clean

def filter_tickers(tickers: list[str]) -> list[dict]:
    """Filter tickers by market cap and sector"""
    results = []
    batch_size = 50
    for i in tqdm(range(0, len(tickers), batch_size), desc="Filtering tickers"):
        batch = tickers[i:i + batch_size]
        try:
            info = yf.download(batch, period="1d", progress=False, group_by="ticker")
        except Exception:
            continue
        for t in batch:
            try:
                tk = yf.Ticker(t)
                tk_info = tk.info
                mcap = tk_info.get("marketCap", 0) or 0
                sector = tk_info.get("sector", "")
                if mcap < SCREENER_MIN_MARKET_CAP:
                    continue
                if sector in SCREENER_EXCLUDE_SECTORS:
                    continue
                results.append({
                    "ticker": t,
                    "name": tk_info.get("longName", ""),
                    "sector": sector,
                    "industry": tk_info.get("industry", ""),
                    "market_cap": mcap,
                    "volume_avg": tk_info.get("averageVolume", 0),
                })
            except Exception:
                continue
    return results

def run():
    print("Fetching all US tickers...")
    tickers = get_all_tickers()
    print(f"Total raw tickers: {len(tickers)}")
    filtered = filter_tickers(tickers)
    df = pd.DataFrame(filtered).sort_values("market_cap", ascending=False)
    path = "/mnt/c/Users/Roma/IdeaProjects/trading-by-K8/data/raw/tickers_filtered.csv"
    df.to_csv(path, index=False)
    print(f"Filtered {len(df)} tickers -> {path}")
    return df

if __name__ == "__main__":
    run()
