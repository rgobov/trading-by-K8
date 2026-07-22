import pandas as pd
import numpy as np
from src.config import (
    FILTER_K_THRESHOLD,
    FILTER_MIN_QUARTERS_ABOVE,
    FILTER_MIN_LOOKBACK_QUARTERS,
    DATA_PROCESSED,
)

def load_k_ratings() -> pd.DataFrame:
    path = f"{DATA_PROCESSED}/all_K_ratings.csv"
    return pd.read_csv(path) if pd.io.common.file_exists(path) else pd.DataFrame()

def load_ticker_k(ticker: str) -> pd.DataFrame:
    path = f"{DATA_PROCESSED}/{ticker}_K.csv"
    try:
        return pd.read_csv(path)
    except FileNotFoundError:
        return pd.DataFrame()

def filter_by_k_stability(
    df_k: pd.DataFrame,
    threshold: float = FILTER_K_THRESHOLD,
    min_above: int = FILTER_MIN_QUARTERS_ABOVE,
    lookback: int = FILTER_MIN_LOOKBACK_QUARTERS,
) -> pd.DataFrame:
    """Filter tickers where K > threshold in at least min_above of last lookback quarters"""
    qualified = []
    for _, row in df_k.iterrows():
        ticker = row["ticker"]
        quarters = load_ticker_k(ticker)
        if quarters.empty or len(quarters) < lookback:
            continue
        recent = quarters.head(lookback)
        above = (recent["K"] > threshold).sum()
        if above >= min_above:
            qualified.append({
                "ticker": ticker,
                "avg_K": row.get("avg_K", 0),
                "latest_K": row.get("latest_K", 0),
                "quarters_above": above,
                "K_trend": "stable" if recent["K"].iloc[0] > recent["K"].iloc[-1] else "declining",
            })
    result = pd.DataFrame(qualified).sort_values("avg_K", ascending=False)
    path = f"{DATA_PROCESSED}/filtered_candidates.csv"
    result.to_csv(path, index=False)
    print(f"Filtered {len(result)} candidates -> {path}")
    return result

def rank_by_sector(df: pd.DataFrame, tickers_meta: pd.DataFrame = None) -> pd.DataFrame:
    """Group filtered candidates by sector and rank within each"""
    if tickers_meta is not None:
        df = df.merge(tickers_meta[["ticker", "sector"]], on="ticker", how="left")
    if "sector" in df.columns:
        df["sector_rank"] = df.groupby("sector")["avg_K"].rank(ascending=False)
        df = df.sort_values(["sector", "sector_rank"])
    return df

def run(tickers_meta: pd.DataFrame = None) -> pd.DataFrame:
    print("Loading K ratings...")
    df_k = load_k_ratings()
    if df_k.empty:
        print("No K ratings found. Run calculator first.")
        return pd.DataFrame()
    print(f"Loaded {len(df_k)} tickers with K scores")
    df_filtered = filter_by_k_stability(df_k)
    if df_filtered.empty:
        print("No tickers passed the filter")
        return df_filtered
    df_ranked = rank_by_sector(df_filtered, tickers_meta)
    print("\nTop candidates by sector:")
    print(df_ranked.head(20).to_string(index=False))
    return df_ranked

if __name__ == "__main__":
    run()
