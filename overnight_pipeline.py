#!/usr/bin/env python3
"""Overnight pipeline: complete S&P 500 SEC parsing → K → filter → backtest → ML"""
import sys, os, json, time, glob, pickle, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from tqdm import tqdm
from datetime import datetime

from src.config import DATA_RAW, DATA_PROCESSED, OUTPUT_DIR
from src.edgar_parser import get_fundamentals
from src.calculator import calc_k_for_ticker
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

# 1. Load S&P 500 tickers
tickers_df = pd.read_csv(f"{DATA_RAW}/sp500_tickers.csv")
all_tickers = tickers_df["ticker"].tolist()
log(f"S&P 500 tickers: {len(all_tickers)}")

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
    except:
        pass
    time.sleep(0.12)

available = [f.replace("_fundamentals.csv", "") for f in os.listdir(DATA_RAW) if f.endswith("_fundamentals.csv")]
log(f"SEC parsed total: {len(available)}")

# 4. Calculate K
log("Calculating K...")
rows = []
for t in tqdm(available, desc="K"):
    r = calc_k_for_ticker(t)
    if "error" not in r:
        qs = r.get("quarters", [])
        rows.append({"ticker": t, "avg_K": r.get("avg_K",0), "latest_K": qs[-1]["K"] if qs else 0, "qcount": len(qs)})

df_k = pd.DataFrame(rows).sort_values("avg_K", ascending=False)
df_k_path = f"{DATA_PROCESSED}/all_K_ratings.csv"
df_k.to_csv(df_k_path, index=False)
log(f"K ratings: {len(df_k)}. Top: {df_k.head(5)['ticker'].tolist()}")

# 5. Filter
df_f = filter_by_k_stability(df_k, threshold=1.1, min_above=2, lookback=3)
df_f["sector"] = df_f["ticker"].map(sectors)
excl = {"Financial Services", "Insurance", "Banks", "Capital Markets",
        "Utilities", "Real Estate", "Energy"}
df_f = df_f[~df_f["sector"].isin(excl)]
df_f = df_f[df_f["sector"].notna()]
df_f = df_f[df_f["sector"] != ""]
df_f.to_csv(f"{DATA_PROCESSED}/filtered_candidates.csv", index=False)
log(f"Candidates: {len(df_f)}")
log(f"Sectors: {df_f['sector'].value_counts().to_dict()}")

# 6. Backtest — both variants
log("Backtesting...")
results = {}
for label, compounding in [("compounding", True), ("fixed", False)]:
    bt = Backtest(initial_capital=1500, k_weighted=True, compounding=compounding)
    bt.run_for_candidates(df_f, years=3)
    s = bt.get_summary()
    results[label] = s
    CAGR = ((s["final_capital"] / 1500) ** (1/3) - 1) * 100
    log(f"  {label}: return={s['total_return_pct']:.2f}% CAGR={CAGR:.2f}% trades={s['total_trades']} win={s['win_rate']}%")

# 7. ML
log("Training ML...")
trades = pd.read_csv(f"{DATA_PROCESSED}/backtest_trades.csv")
if not trades.empty and len(trades) >= 30:
    trades["target"] = (trades["pnl_pct"] > 0).astype(int)
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, precision_score
    feat_list = []
    for t in trades["ticker"].unique():
        try:
            kdf = pd.read_csv(f"{DATA_PROCESSED}/{t}_K.csv")
            if not kdf.empty:
                feat_list.append({"ticker": t, "K_avg": kdf["K"].mean(), "K_latest": kdf["K"].iloc[0],
                                  "KI_avg": kdf["KI"].mean(), "KR_avg": kdf["KR"].mean(), "KF_avg": kdf["KF"].mean()})
        except: pass
    df_feat = pd.DataFrame(feat_list)
    merged = trades.merge(df_feat, on="ticker", how="left").dropna()
    if len(merged) >= 50:
        X = merged[["K_avg", "K_latest", "KI_avg", "KR_avg", "KF_avg"]]
        y = merged["target"]
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.3, random_state=42)
        model = RandomForestClassifier(n_estimators=200, max_depth=5, random_state=42)
        model.fit(X_tr, y_tr)
        y_p = model.predict(X_te)
        acc = accuracy_score(y_te, y_p)
        prec = precision_score(y_te, y_p, zero_division=0)
        log(f"ML accuracy={acc:.2%} precision={prec:.2%}")
        for n, i in sorted(zip(X.columns, model.feature_importances_), key=lambda x: -x[1]):
            log(f"  {n}: {i:.3f}")
        with open(f"{OUTPUT_DIR}/ml_model.pkl", "wb") as f:
            pickle.dump(model, f)

# 8. Summary
log(f"\n{'='*60}")
log(f"  FINAL SUMMARY")
log(f"{'='*60}")
log(f"  S&P 500 parsed:   {len(available)}/{len(all_tickers)}")
log(f"  K > 1.1 filter:   {len(df_f)} candidates")
log(f"  Compounding:      {results.get('compounding',{}).get('total_return_pct',0):.2f}% ({results.get('compounding',{}).get('total_trades',0)} trades)")
log(f"  Fixed:            {results.get('fixed',{}).get('total_return_pct',0):.2f}% ({results.get('fixed',{}).get('total_trades',0)} trades)")
log(f"  Win rate:         ~{results.get('fixed',{}).get('win_rate',0)}%")
log(f"{'='*60}")

log("=== PIPELINE COMPLETE ===")
