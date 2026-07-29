#!/usr/bin/env python3
"""Overnight pipeline: SEC → K → filter → backtest (two-pass), for all universes."""
import sys, os, json, time, glob, warnings, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

import pandas as pd
from tqdm import tqdm
from datetime import datetime

from src.config import (
    DATA_RAW, DATA_PROCESSED, OUTPUT_DIR, FILTER_EXCLUDE_SECTORS,
    UNIVERSE_RUSSELL, UNIVERSE_SP500,
)
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

# 1. Load all tickers from all supported universes (dedup)
UNIVERSES = {
    UNIVERSE_RUSSELL: {"file": "russell1000_tickers.csv", "col": "ticker"},
    UNIVERSE_SP500: {"file": "sp500_tickers.csv", "col": "Symbol"},
}
all_tickers = set()
for name, spec in UNIVERSES.items():
    path = f"{DATA_RAW}/{spec['file']}"
    if os.path.exists(path):
        df = pd.read_csv(path)
        tickers = df[spec["col"]].str.strip().tolist()
        all_tickers.update(tickers)
        log(f"{name}: {len(tickers)} tickers")
    else:
        log(f"{name}: file not found ({spec['file']}), skipping")

all_tickers = sorted(all_tickers)
log(f"Total unique tickers: {len(all_tickers)}")

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

# 5-7. For each universe: filter + backtest (two-pass)
def process_universe(universe_name: str, universe_tickers: list[str]):
    log(f"\n{'='*50}")
    log(f"Processing universe: {universe_name} ({len(universe_tickers)} tickers)")
    log(f"{'='*50}")

    # Filter K data to universe tickers
    df_u = df_k[df_k["ticker"].isin(universe_tickers)].copy()
    log(f"Universe tickers with K data: {len(df_u)}")

    # Filter — sector-specific thresholds (Technology stricter)
    log("Filtering candidates...")
    strict_sectors = {"Technology"}
    tech_df = df_u[df_u["sector"].isin(strict_sectors)]
    other_df = df_u[~df_u["sector"].isin(strict_sectors)]

    tech_f = filter_by_k_stability(tech_df, threshold=1.3, min_above=3, lookback=3)
    other_f = filter_by_k_stability(other_df, threshold=1.1, min_above=2, lookback=3)

    df_f = pd.concat([tech_f, other_f], ignore_index=True)
    df_f["sector"] = df_f["ticker"].map(sectors)
    df_f = df_f[~df_f["sector"].isin(FILTER_EXCLUDE_SECTORS)]
    df_f = df_f[df_f["sector"].notna()]
    df_f = df_f[df_f["sector"] != ""]
    candidates_path = f"{DATA_PROCESSED}/filtered_candidates_{universe_name}.csv"
    df_f.to_csv(candidates_path, index=False)
    log(f"Candidates ({universe_name}): {len(df_f)}")
    log(f"Sectors: {df_f['sector'].value_counts().to_dict()}")

    if df_f.empty:
        log(f"No candidates for {universe_name}, skipping backtest")
        return

    # Pass 1 — all candidates → find repeat offenders
    log("Pass 1 — backtesting all candidates to find repeat offenders...")
    bt1 = Backtest(initial_capital=1500, k_weighted=True, compounding=False)
    bt1.run_for_candidates(df_f, years=5, sectors_map=sectors)
    trades_path = f"{DATA_PROCESSED}/backtest_trades.csv"
    trades = pd.read_csv(trades_path) if os.path.exists(trades_path) else pd.DataFrame()
    pass1_offenders = set()
    if not trades.empty:
        for ticker, grp in trades.groupby("ticker"):
            if len(grp) >= 10 and grp["pnl"].sum() < 0:
                pass1_offenders.add(ticker)

    log(f"Pass 1 repeat offenders ({len(pass1_offenders)}): {sorted(pass1_offenders) if pass1_offenders else 'none'}")
    repeat_path = f"{DATA_PROCESSED}/repeat_offenders_{universe_name}.json"
    json.dump(sorted(pass1_offenders), open(repeat_path, "w"))

    # Pass 2 — exclude repeat offenders, both variants
    if pass1_offenders:
        df_f = df_f[~df_f["ticker"].isin(pass1_offenders)].copy()
        log(f"Pass 2 candidates ({universe_name}): {len(df_f)}")
    df_f.to_csv(candidates_path, index=False)

    results = {}
    for label, compounding in [("compounding", True), ("fixed", False)]:
        bt = Backtest(initial_capital=1500, k_weighted=True, compounding=compounding)
        bt.run_for_candidates(df_f, years=5, sectors_map=sectors)
        s = bt.get_summary()
        results[label] = s
        CAGR = ((s["final_capital"] / 1500) ** (1/5) - 1) * 100
        log(f"  {label} ({universe_name}): return={s['total_return_pct']:.2f}% CAGR={CAGR:.2f}% trades={s['total_trades']} win={s['win_rate']}%")
        src = f"{DATA_PROCESSED}/backtest_trades.csv"
        if os.path.exists(src):
            shutil.copy(src, f"{DATA_PROCESSED}/backtest_trades_{universe_name}_{label}.csv")

    comp = results.get("compounding", {})
    fix = results.get("fixed", {})
    cagr_c = ((comp.get("final_capital", 1500) / 1500) ** (1/5) - 1) * 100 if comp else 0
    cagr_f = ((fix.get("final_capital", 1500) / 1500) ** (1/5) - 1) * 100 if fix else 0
    log(f"\n  {'-'*60}")
    log(f"  RESULTS — {universe_name}")
    log(f"  {'Strategy':15s} {'Return':>10s} {'CAGR':>7s} {'WR':>5s} {'DD':>7s} {'Trades':>7s}")
    log(f"  {'-'*15} {'-'*10} {'-'*7} {'-'*5} {'-'*7} {'-'*7}")
    log(f"  {'Fixed':15s} {fix.get('total_return_pct',0):>9.1f}% {cagr_f:>6.1f}% {fix.get('win_rate',0):>4.1f}% {fix.get('max_drawdown_pct',0):>6.1f}% {fix.get('total_trades',0):>6d}")
    log(f"  {'Compounding':15s} {comp.get('total_return_pct',0):>9.1f}% {cagr_c:>6.1f}% {comp.get('win_rate',0):>4.1f}% {comp.get('max_drawdown_pct',0):>6.1f}% {comp.get('total_trades',0):>6d}")

# Process each universe
for name, spec in UNIVERSES.items():
    path = f"{DATA_RAW}/{spec['file']}"
    if os.path.exists(path):
        df = pd.read_csv(path)
        tickers = df[spec["col"]].str.strip().tolist()
        process_universe(name, tickers)

log(f"\n{'='*68}")
log(f"PIPELINE COMPLETE — all universes processed")
log(f"{'='*68}")
