#!/usr/bin/env python3
"""Overnight pipeline: SEC → K → filter → backtest (two-pass)"""
import sys, os, json, time, glob, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

import pandas as pd
from tqdm import tqdm
from datetime import datetime

from src.config import DATA_RAW, DATA_PROCESSED, OUTPUT_DIR, FILTER_EXCLUDE_SECTORS
from src.edgar_parser import get_fundamentals
from src.calculator import run_k_all
from src.filter import filter_by_k_stability
from src.backtest import Backtest

os.makedirs(DATA_RAW, exist_ok=True)
os.makedirs(DATA_PROCESSED, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
LOG = f"{OUTPUT_DIR}/pipeline_log.txt"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

log("=== OVERNIGHT PIPELINE START ===")

# 1. Load Russell 1000 tickers
tickers_df = pd.read_csv(f"{DATA_RAW}/russell1000_tickers.csv")
all_tickers = tickers_df["ticker"].tolist()
log(f"Russell 1000 tickers: {len(all_tickers)}")

# 2. Load sector info
sectors_path = f"{DATA_RAW}/ticker_sectors.json"
if os.path.exists(sectors_path):
    with open(sectors_path) as f:
        sectors = json.load(f)
else:
    sectors = {}
need_sectors = [t for t in all_tickers if t not in sectors]
log(f"Sectors needed: {len(need_sectors)}")

if need_sectors:
    import yfinance as yf
    for t in tqdm(need_sectors, desc="Sectors"):
        try:
            info = yf.Ticker(t).info
            sectors[t] = info.get("sector", "")
        except:
            sectors[t] = ""
        time.sleep(0.03)
    with open(sectors_path, "w") as f:
        json.dump(sectors, f)
    log(f"Sectors cached: {len(sectors)}")

# 3. Parse SEC fundamentals
already = set(f.replace("_fundamentals.csv", "") for f in os.listdir(DATA_RAW) if f.endswith("_fundamentals.csv"))
need_parse = [t for t in all_tickers if t not in already]
log(f"SEC parsed already: {len(already)}, need: {len(need_parse)}")

for t in tqdm(need_parse, desc="SEC"):
    try:
        df = get_fundamentals(t)
        if not df.empty:
            df.to_csv(f"{DATA_RAW}/{t}_fundamentals.csv", index=False)
        else:
            open(f"{DATA_RAW}/{t}_fundamentals.csv", "w").close()
    except:
        open(f"{DATA_RAW}/{t}_fundamentals.csv", "w").close()
    time.sleep(0.12)

available = [f.replace("_fundamentals.csv", "") for f in os.listdir(DATA_RAW) if f.endswith("_fundamentals.csv")]
log(f"SEC parsed total: {len(available)}")

# 4. Calculate K with sector-level competition
log("Calculating K (sector-competitive)...")
df_k = run_k_all(available, sectors)
log(f"K ratings: {len(df_k)}. Top: {df_k.head(5)['ticker'].tolist() if len(df_k) >= 5 else df_k['ticker'].tolist()}")

# 5. Filter — sector-specific thresholds (Technology stricter)
log("Filtering candidates...")
strict_sectors = {"Technology"}
tech_df = df_k[df_k["sector"].isin(strict_sectors)]
other_df = df_k[~df_k["sector"].isin(strict_sectors)]

tech_f = filter_by_k_stability(tech_df, threshold=1.3, min_above=3, lookback=3)
other_f = filter_by_k_stability(other_df, threshold=1.1, min_above=2, lookback=3)

df_f = pd.concat([tech_f, other_f], ignore_index=True)
df_f["sector"] = df_f["ticker"].map(sectors)
df_f = df_f[~df_f["sector"].isin(FILTER_EXCLUDE_SECTORS)]
df_f = df_f[df_f["sector"].notna()]
df_f = df_f[df_f["sector"] != ""]
df_f.to_csv(f"{DATA_PROCESSED}/filtered_candidates.csv", index=False)
log(f"Candidates: {len(df_f)}")
log(f"Sectors: {df_f['sector'].value_counts().to_dict()}")

# 6. Backtest — pass 1: all candidates → find repeat offenders
log("Pass 1 — backtesting all candidates to find repeat offenders...")
repeat_offenders_path = f"{DATA_PROCESSED}/repeat_offenders.json"
bt1 = Backtest(initial_capital=1500, k_weighted=True, compounding=False)
bt1.run_for_candidates(df_f, years=5, sectors_map=sectors)
trades = pd.read_csv(f"{DATA_PROCESSED}/backtest_trades.csv")
pass1_offenders = set()
for ticker, grp in trades.groupby("ticker"):
    if len(grp) >= 10 and (grp["pnl"] > 0).mean() < 0.40:
        pass1_offenders.add(ticker)

log(f"Pass 1 repeat offenders ({len(pass1_offenders)}): {sorted(pass1_offenders) if pass1_offenders else 'none'}")
json.dump(sorted(pass1_offenders), open(repeat_offenders_path, "w"))

# 7. Backtest — pass 2: exclude repeat offenders, both variants
if pass1_offenders:
    df_f = df_f[~df_f["ticker"].isin(pass1_offenders)].copy()
    log(f"Pass 2 candidates: {len(df_f)}")
df_f.to_csv(f"{DATA_PROCESSED}/filtered_candidates.csv", index=False)

results = {}
for label, compounding in [("compounding", True), ("fixed", False)]:
    bt = Backtest(initial_capital=1500, k_weighted=True, compounding=compounding)
    bt.run_for_candidates(df_f, years=5, sectors_map=sectors)
    s = bt.get_summary()
    results[label] = s
    CAGR = ((s["final_capital"] / 1500) ** (1/5) - 1) * 100
    log(f"  {label}: return={s['total_return_pct']:.2f}% CAGR={CAGR:.2f}% trades={s['total_trades']} win={s['win_rate']}%")
    # Save variant-specific trades (backtest.py overwrites the generic file each call)
    src = f"{DATA_PROCESSED}/backtest_trades.csv"
    if os.path.exists(src):
        import shutil
        shutil.copy(src, f"{DATA_PROCESSED}/backtest_trades_{label}.csv")

# 8. Summary
comp = results.get("compounding", {})
fix = results.get("fixed", {})
cagr_c = ((comp.get("final_capital", 1500) / 1500) ** (1/5) - 1) * 100 if comp else 0
cagr_f = ((fix.get("final_capital", 1500) / 1500) ** (1/5) - 1) * 100 if fix else 0
log(f"\n{'='*68}")
log(f"  FINAL SUMMARY")
log(f"{'='*68}")
log(f"  Russell 1000 parsed:   {len(available)}/{len(all_tickers)}")
log(f"  Candidates:            {len(df_f)}")
log(f"  {'Strategy':15s} {'Return':>10s} {'CAGR':>7s} {'WR':>5s} {'DD':>7s} {'Trades':>7s}")
log(f"  {'-'*15} {'-'*10} {'-'*7} {'-'*5} {'-'*7} {'-'*7}")
log(f"  {'Fixed':15s} {fix.get('total_return_pct',0):>9.1f}% {cagr_f:>6.1f}% {fix.get('win_rate',0):>4.1f}% {fix.get('max_drawdown_pct',0):>6.1f}% {fix.get('total_trades',0):>6d}")
log(f"  {'Compounding':15s} {comp.get('total_return_pct',0):>9.1f}% {cagr_c:>6.1f}% {comp.get('win_rate',0):>4.1f}% {comp.get('max_drawdown_pct',0):>6.1f}% {comp.get('total_trades',0):>6d}")
log(f"{'='*68}")

log("=== PIPELINE COMPLETE ===")
