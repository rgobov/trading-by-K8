#!/usr/bin/env python3
"""Full pipeline: screener → SEC parser → K calc → filter → backtest → ML"""
import sys, os, json, pickle, time, warnings
import pandas as pd
import numpy as np
from tqdm import tqdm
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.config import DATA_RAW, DATA_PROCESSED, OUTPUT_DIR
from src.screener import get_all_tickers, filter_tickers
from src.edgar_parser import get_fundamentals
from src.calculator import calc_k_for_ticker
from src.filter import filter_by_k_stability
from src.backtest import Backtest
from src.backtest import Backtest

warnings.filterwarnings("ignore")
pd.set_option("display.max_rows", 20)
pd.set_option("display.width", 120)

def stage(msg):
    print(f"\n{'='*70}")
    print(f"  {msg}")
    print(f"{'='*70}")

def get_ticker_sectors(tickers: list[str]) -> dict:
    """Get sector for each ticker from yfinance"""
    stage(f"Fetching sectors for {len(tickers)} tickers")
    sectors = {}
    batch = []
    for t in tqdm(tickers, desc="Sectors"):
        try:
            import yfinance as yf
            tk = yf.Ticker(t)
            info = tk.info
            sector = info.get("sector", "")
            sectors[t] = sector
        except Exception:
            sectors[t] = ""
        time.sleep(0.05)
    return sectors

def run_screener(max_tickers: int = 500) -> pd.DataFrame:
    stage("SCREENER: Getting tickers")
    all_t = get_all_tickers()
    print(f"  Raw tickers: {len(all_t)}")

    used = []
    for t in all_t:
        if len(used) >= max_tickers:
            break
        if t == "BRK-B":
            continue
        used.append(t)

    df = pd.DataFrame({"ticker": used})
    path = f"{DATA_RAW}/pipeline_tickers.csv"
    df.to_csv(path, index=False)
    print(f"  Selected {len(used)} tickers -> {path}")
    return df

def run_parser(tickers: list[str]):
    stage(f"SEC EDGAR PARSER: {len(tickers)} tickers")
    ok = 0
    for t in tqdm(tickers, desc="Parsing"):
        try:
            df = get_fundamentals(t)
            if not df.empty:
                df.to_csv(f"{DATA_RAW}/{t}_fundamentals.csv", index=False)
                ok += 1
        except Exception:
            pass
        time.sleep(0.12)
    print(f"  Parsed: {ok}/{len(tickers)}")
    return ok

def run_k_calc() -> pd.DataFrame:
    stage("K CALCULATOR")
    import glob
    files = glob.glob(f"{DATA_RAW}/*_fundamentals.csv")
    tickers = sorted(set(f.replace("_fundamentals.csv", "").split("/")[-1] for f in files))
    print(f"  {len(tickers)} tickers with fundamentals")

    rows = []
    for t in tqdm(tickers, desc="K calc"):
        result = calc_k_for_ticker(t)
        if "error" not in result:
            qs = result.get("quarters", [])
            rows.append({
                "ticker": t,
                "avg_K": result.get("avg_K", 0),
                "latest_K": qs[-1]["K"] if qs else 0,
                "quarter_count": len(qs),
            })

    df = pd.DataFrame(rows).sort_values("avg_K", ascending=False)
    df.to_csv(f"{DATA_PROCESSED}/all_K_ratings.csv", index=False)
    print(f"  {len(df)} K ratings computed")
    return df

def run_filter(df_k: pd.DataFrame, sectors: dict = None) -> pd.DataFrame:
    stage("FILTER")
    df_f = filter_by_k_stability(df_k, threshold=1.1, min_above=2, lookback=3)
    print(f"  Before sector filter: {len(df_f)}")

    if sectors and "ticker" in df_f.columns:
        df_f["sector"] = df_f["ticker"].map(sectors)
        from src.config import FILTER_EXCLUDE_SECTORS
        before = len(df_f)
        df_f = df_f[~df_f["sector"].isin(FILTER_EXCLUDE_SECTORS)]
        df_f = df_f[df_f["sector"] != ""]
        print(f"  After excluding sectors: {len(df_f)} (removed {before - len(df_f)})")
        print(f"  Sector breakdown: {df_f['sector'].value_counts().to_dict()}")

    df_f.to_csv(f"{DATA_PROCESSED}/filtered_candidates.csv", index=False)
    return df_f

def run_backtest(df_f: pd.DataFrame) -> Backtest:
    stage("BACKTEST")
    bt = Backtest(initial_capital=1500)
    bt.run_for_candidates(df_f, years=3)
    s = bt.get_summary()
    print(f"  Total return: {s['total_return_pct']}%")
    print(f"  Win rate: {s['win_rate']}%")
    print(f"  Trades: {s['total_trades']}")
    return bt

def run_ml(df_f: pd.DataFrame, bt: Backtest):
    stage("ML MODEL: Training classifier on K features")
    try:
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score, precision_score

        trades = pd.DataFrame(bt.trades)
        if trades.empty or len(trades) < 20:
            print("  Not enough trades for ML, skipping")
            return

        trades["target"] = (trades["pnl_pct"] > 0).astype(int)
        tickets = trades["ticker"].unique()
        print(f"  {len(trades)} trades, {len(tickets)} tickers")

        features = []
        for t in tickets:
            k_file = f"{DATA_PROCESSED}/{t}_K.csv"
            try:
                kdf = pd.read_csv(k_file)
            except:
                continue
            if kdf.empty:
                continue
            avg = kdf["K"].mean()
            latest = kdf["K"].iloc[0]
            ki_avg = kdf["KI"].mean()
            kr_avg = kdf["KR"].mean()
            kf_avg = kdf["KF"].mean()
            features.append({
                "ticker": t,
                "K_avg": avg,
                "K_latest": latest,
                "KI_avg": ki_avg,
                "KR_avg": kr_avg,
                "KF_avg": kf_avg,
            })

        df_feat = pd.DataFrame(features)
        merged = trades.merge(df_feat, on="ticker", how="left").dropna()
        if len(merged) < 20:
            print("  Too few samples after merge, skipping")
            return

        X = merged[["K_avg", "K_latest", "KI_avg", "KR_avg", "KF_avg"]]
        y = merged["target"]

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)
        model = RandomForestClassifier(n_estimators=100, max_depth=3, random_state=42)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        acc = accuracy_score(y_test, y_pred)
        prec = precision_score(y_test, y_pred, zero_division=0)
        print(f"\n  ML RESULTS:")
        print(f"  Accuracy:  {acc:.2%}")
        print(f"  Precision: {prec:.2%}")
        print(f"  Feature importances:")
        for name, imp in sorted(zip(X.columns, model.feature_importances_), key=lambda x: -x[1]):
            print(f"    {name}: {imp:.3f}")

        model_path = f"{OUTPUT_DIR}/ml_model.pkl"
        with open(model_path, "wb") as f:
            pickle.dump(model, f)
        print(f"  Model saved -> {model_path}")
    except ImportError:
        print("  sklearn not installed, skipping ML")
    except Exception as e:
        print(f"  ML error: {e}")

def main():
    os.makedirs(DATA_RAW, exist_ok=True)
    os.makedirs(DATA_PROCESSED, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    df_t = run_screener(max_tickers=500)
    tickers = df_t["ticker"].tolist()

    sectors = get_ticker_sectors(tickers)
    with open(f"{DATA_RAW}/ticker_sectors.json", "w") as f:
        json.dump(sectors, f)

    run_parser(tickers)

    df_k = run_k_calc()
    df_f = run_filter(df_k, sectors)

    if not df_f.empty:
        bt = run_backtest(df_f)
        run_ml(df_f, bt)
    else:
        print("\nNo candidates passed filter, adjust thresholds")

    print("\nDone!")

if __name__ == "__main__":
    main()
