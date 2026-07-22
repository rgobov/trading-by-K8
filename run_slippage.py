#!/usr/bin/env python3
"""Run backtest on existing data with slippage + 5 years"""
import sys, os, json, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

import pandas as pd
from datetime import datetime
from src.config import DATA_PROCESSED
from src.backtest import Backtest

LOG = f"{DATA_PROCESSED}/slippage_results.txt"

results = []
for years, label in [(3, "3yr"), (5, "5yr")]:
    for compounding in [True, False]:
        mode = "compound" if compounding else "fixed"
        bt = Backtest(initial_capital=1500, k_weighted=True, compounding=compounding)

        bt.run_for_candidates(
            pd.read_csv(f"{DATA_PROCESSED}/filtered_candidates.csv"),
            years=years
        )
        s = bt.get_summary()
        CAGR = ((s["final_capital"] / 1500) ** (1/years) - 1) * 100
        line = f"{label}/{mode}: return={s['total_return_pct']:.1f}% CAGR={CAGR:.1f}% trades={s['total_trades']} win={s['win_rate']}% final=${s['final_capital']:.0f}"
        results.append(line)
        print(line)
        with open(LOG, "a") as f:
            f.write(line + "\n")

print(f"\nDone. Results in {LOG}")
PYEOF
