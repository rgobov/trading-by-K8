import pandas as pd
import numpy as np
from src.config import DATA_RAW, DATA_PROCESSED

def calc_ki(ia: float, is_: float) -> float:
    """Коэффициент стратегического позиционирования"""
    if is_ <= 0:
        return 1.0
    return ia / is_

def calc_kr(ra: float, rs: float) -> float:
    """Коэффициент операционной эффективности"""
    if rs <= 0:
        return 1.0
    return ra / rs

def calc_kf(fa: float, fs: float) -> float:
    """Коэффициент финансового состояния"""
    if fs <= 0:
        return 1.0
    return fa / fs

def calc_ia(s_current: float, s_prev: float) -> float:
    """Индекс изменения выручки"""
    if s_prev <= 0:
        return 1.0
    return s_current / s_prev

def calc_ra(s: float, e: float) -> float:
    """Операционная эффективность = Выручка / Издержки"""
    if e <= 0:
        return 1.0
    return s / e

def calc_fa(ca: float, cl: float) -> float:
    """Уровень ликвидности = ∛(Current Assets / Current Liabilities)"""
    if cl <= 0:
        return 1.0
    ratio = ca / cl
    return np.cbrt(ratio)

def load_ticker_data(ticker: str) -> pd.DataFrame:
    """Load fundamental data from saved CSV"""
    path = f"{DATA_RAW}/{ticker}_fundamentals.csv"
    try:
        return pd.read_csv(path)
    except FileNotFoundError:
        return pd.DataFrame()

def prepare_data(df: pd.DataFrame) -> pd.DataFrame:
    """Sort and prepare quarterly data (oldest first for YoY lookup)"""
    if df.empty:
        return df
    if "end_date" not in df.columns:
        df["end_date"] = df["year"].astype(str) + "-09-30"
    if "fp" not in df.columns:
        df["fp"] = "FY"
    df = df.sort_values("end_date").reset_index(drop=True)
    return df

def calc_k_for_ticker(ticker: str, competitors_df: pd.DataFrame = None) -> dict:
    """Calculate K for a single ticker over available quarters (YoY by same fp type)"""
    df = load_ticker_data(ticker)
    if df.empty:
        return {"ticker": ticker, "error": "no data"}
    df = prepare_data(df)
    df["fp_order"] = df["fp"].map({"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4})
    df = df.sort_values(["year", "fp_order"]).reset_index(drop=True)

    quarters = []
    for i in range(len(df)):
        row = df.iloc[i]
        s = row.get("Revenue", 0) or 0
        ni = row.get("NetIncome", 0) or 0
        ca = row.get("CurrentAssets", 0) or 0
        cl = row.get("CurrentLiabilities", 0) or 0
        e = s - ni if (s and ni is not None) else 0

        # YoY: find same quarter (fp) from previous year
        fp = row.get("fp", "FY")
        year = row.get("year", 0)
        prev_rev = None
        for j in range(i - 1, -1, -1):
            prev = df.iloc[j]
            if prev.get("fp") == fp and prev.get("year", 0) < year:
                prev_rev = prev.get("Revenue", 0) or 0
                break
        s_prev = prev_rev if prev_rev is not None and prev_rev > 0 else s
        ia = calc_ia(s, s_prev)
        ra = calc_ra(s, e) if e > 0 else 1.0
        fa = calc_fa(ca, cl) if cl > 0 else 1.0
        quarters.append({
            "year": year,
            "fp": fp,
            "IA": ia,
            "RA": ra,
            "FA": fa,
            "Revenue": s,
            "NetIncome": ni,
            "CurrentAssets": ca,
            "CurrentLiabilities": cl,
            "Expenses": e,
            "Revenue_prev": s_prev,
        })
    if not quarters:
        return {"ticker": ticker, "error": "no quarters"}
    comp_quarters = []
    if competitors_df is not None and not competitors_df.empty:
        comp_quarters = prepare_data(competitors_df).to_dict("records")
    results = []
    for i, q in enumerate(quarters):
        ia, ra, fa = q["IA"], q["RA"], q["FA"]
        is_, rs, fs = 1.0, 1.0, 1.0
        if i < len(comp_quarters):
            cq = comp_quarters[i]
            s_c = cq.get("Revenue", 0) or 0
            ni_c = cq.get("NetIncome", 0) or 0
            e_c = s_c - ni_c if (s_c and ni_c is not None) else 0
            ca_c = cq.get("CurrentAssets", 0) or 0
            cl_c = cq.get("CurrentLiabilities", 0) or 0
            s_prev_c = comp_quarters[i + 1].get("Revenue", s_c) if i + 1 < len(comp_quarters) else s_c
            is_ = calc_ia(s_c, s_prev_c)
            rs = calc_ra(s_c, e_c) if e_c > 0 else 1.0
            fs = calc_fa(ca_c, cl_c) if cl_c > 0 else 1.0
        ki = calc_ki(ia, is_)
        kr = calc_kr(ra, rs)
        kf = calc_kf(fa, fs)
        k = ki * kr * kf
        results.append({
            "ticker": ticker,
            "year": q["year"],
            "K": round(k, 4),
            "KI": round(ki, 4),
            "KR": round(kr, 4),
            "KF": round(kf, 4),
            "IA": round(ia, 4),
            "RA": round(ra, 4),
            "FA": round(fa, 4),
            "IS": round(is_, 4),
            "RS": round(rs, 4),
            "FS": round(fs, 4),
        })
    df_out = pd.DataFrame(results)
    df_out.to_csv(f"{DATA_PROCESSED}/{ticker}_K.csv", index=False)
    return {"ticker": ticker, "quarters": results, "avg_K": round(np.mean([r["K"] for r in results]), 4) if results else 0}

def run_for_tickers(tickers: list[str]) -> pd.DataFrame:
    """Run K calculation for a list of tickers"""
    all_results = []
    for ticker in tickers:
        result = calc_k_for_ticker(ticker)
        if "error" in result:
            continue
        all_results.append({
            "ticker": ticker,
            "avg_K": result.get("avg_K", 0),
            "latest_K": result["quarters"][0]["K"] if result.get("quarters") else 0,
            "quarter_count": len(result.get("quarters", [])),
        })
    df = pd.DataFrame(all_results).sort_values("avg_K", ascending=False)
    df.to_csv(f"{DATA_PROCESSED}/all_K_ratings.csv", index=False)
    print(f"K calculation done. Results: {DATA_PROCESSED}/all_K_ratings.csv")
    return df
