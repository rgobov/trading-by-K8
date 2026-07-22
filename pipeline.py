#!/usr/bin/env python3
"""
Pipeline: Screener -> Earnings Calendar -> Calculator -> Filter -> Backtest -> Visualize
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import config
from src.screener import run as run_screener
from src.calculator import run_for_tickers
from src.filter import run as run_filter
from src.backtest import run as run_backtest
from src.visualize import run as run_visualize

def main():
    print("=" * 60)
    print("  ISTS DYNAMIC BACKTEST PIPELINE")
    print("  Investment-Speculative Trading System")
    print("  Based on Voronov's Dynamic Competitiveness Method")
    print("=" * 60)

    step = input("\nWhich step? (1-screener, 2-calculator, 3-filter, 4-backtest, 5-visualize, all): ").strip()

    if step in ("1", "all"):
        print("\n[Step 1] Running ticker screener...")
        df_screener = run_screener()
        print(f"  Found {len(df_screener)} tickers")

    if step in ("2", "all"):
        print("\n[Step 2] Running K calculator...")
        path = f"{config.DATA_PROCESSED}/tickers_filtered.csv"
        if os.path.exists(path):
            df_tickers = pd.read_csv(path)
        else:
            import pandas as pd
            df_tickers = pd.read_csv(f"{config.DATA_RAW}/tickers_filtered.csv")
        test_tickers = df_tickers.head(50)["ticker"].tolist()
        print(f"  Calculating K for {len(test_tickers)} tickers...")
        df_k = run_for_tickers(test_tickers)
        print(f"  Completed. Average K range: {df_k['avg_K'].min():.3f} - {df_k['avg_K'].max():.3f}")

    if step in ("3", "all"):
        print("\n[Step 3] Running filter...")
        df_filtered = run_filter()
        print(f"  {len(df_filtered)} candidates passed filter")

    if step in ("4", "all"):
        print("\n[Step 4] Running backtest...")
        bt = run_backtest()
        if bt and bt.trades:
            print(f"  Backtest complete: {len(bt.trades)} trades")

    if step in ("5", "all"):
        print("\n[Step 5] Generating visualizations...")
        run_visualize()

    print("\nDone!")

if __name__ == "__main__":
    import pandas as pd
    main()
