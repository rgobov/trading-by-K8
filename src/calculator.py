import pandas as pd
import numpy as np
from src.config import DATA_RAW, DATA_PROCESSED

def calc_ki(ia: float, is_: float) -> float:
    if is_ <= 0:
        return 1.0
    return ia / is_

def calc_kr(ra: float, rs: float) -> float:
    if rs <= 0:
        return 1.0
    return ra / rs

def calc_kf(fa: float, fs: float) -> float:
    if fs <= 0:
        return 1.0
    return fa / fs

def calc_ia(s_current: float, s_prev: float) -> float:
    if s_prev <= 0:
        return 1.0
    return s_current / s_prev

def calc_ra(s: float, e: float) -> float:
    if e <= 0:
        return 1.0
    return s / e

def calc_fa(ca: float, cl: float) -> float:
    if cl <= 0:
        return 1.0
    ratio = ca / cl
    return np.cbrt(ratio)

def load_ticker_data(ticker: str) -> pd.DataFrame:
    path = f"{DATA_RAW}/{ticker}_fundamentals.csv"
    try:
        df = pd.read_csv(path)
        return df if not df.empty else pd.DataFrame()
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()

def prepare_data(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if "end_date" not in df.columns:
        df["end_date"] = df["year"].astype(str) + "-09-30"
    if "fp" not in df.columns:
        df["fp"] = "FY"
    df = df.sort_values("end_date").reset_index(drop=True)
    return df


def load_fundamentals_cache(tickers: list[str]) -> dict[str, pd.DataFrame]:
    cache = {}
    for t in tickers:
        df = load_ticker_data(t)
        if df.empty:
            continue
        df = prepare_data(df)
        df["fp_order"] = df["fp"].map({"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4})
        df = df.sort_values(["year", "fp_order", "end_date"], ascending=[True, True, False]).reset_index(drop=True)
        df = df.drop_duplicates(subset=["year", "fp"], keep="first").reset_index(drop=True)
        df = df[df["Revenue"].notna() & (df["Revenue"] > 0)]
        if not df.empty:
            cache[t] = df
    return cache

def compute_sector_aggregates(fund_cache: dict[str, pd.DataFrame], sector_tickers: list[str]) -> pd.DataFrame:
    all_quarters = []
    for t in sector_tickers:
        if t not in fund_cache:
            continue
        df = fund_cache[t]
        for i in range(len(df)):
            row = df.iloc[i]
            s = row.get("Revenue", 0) or 0
            ni = row.get("NetIncome", 0) or 0
            ca = row.get("CurrentAssets", 0) or 0
            cl = row.get("CurrentLiabilities", 0) or 0
            e = s - ni if (s and ni is not None) else 0
            yr = row["year"]
            if yr < 2020:
                continue
            all_quarters.append({
                "year": yr,
                "fp": row["fp"],
                "ticker": t,
                "Revenue": s,
                "Expenses": e,
                "CA": ca,
                "CL": cl,
            })
    if not all_quarters:
        return pd.DataFrame()
    df_all = pd.DataFrame(all_quarters)
    company_count = df_all.groupby(["year", "fp"])["ticker"].nunique().reset_index()
    company_count.columns = ["year", "fp", "company_count"]
    agg = df_all.groupby(["year", "fp"]).agg({"Revenue": "sum", "Expenses": "sum", "CA": "sum", "CL": "sum"}).reset_index()
    agg = agg.merge(company_count, on=["year", "fp"])
    agg["fp_order"] = agg["fp"].map({"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4})
    agg = agg.sort_values(["year", "fp_order"]).reset_index(drop=True)
    total_in_sector = len([t for t in sector_tickers if t in fund_cache])
    results = []
    for i in range(len(agg)):
        row = agg.iloc[i]
        fp, year = row["fp"], row["year"]
        count_prev = None
        for j in range(i - 1, -1, -1):
            prev = agg.iloc[j]
            if prev["fp"] == fp and prev["year"] < year:
                count_prev = prev["company_count"]
                s_prev = prev["Revenue"]
                break
        if count_prev is None:
            count_prev = row["company_count"]
            s_prev = row["Revenue"]
        min_coverage = max(3, count_prev * 0.5)
        if row["company_count"] < min_coverage:
            continue
        results.append({
            "year": year, "fp": fp,
            "IS": calc_ia(row["Revenue"], s_prev),
            "RS": calc_ra(row["Revenue"], row["Expenses"]) if row["Expenses"] > 0 else 1.0,
            "FS": calc_fa(row["CA"], row["CL"]) if row["CL"] > 0 else 1.0,
        })
    return pd.DataFrame(results)

def run_k_all(available_tickers: list[str], sectors: dict[str, str]) -> pd.DataFrame:
    fund_cache = load_fundamentals_cache(available_tickers)
    sector_groups = {}
    for t in available_tickers:
        sec = sectors.get(t, "Unknown")
        sector_groups.setdefault(sec, []).append(t)
    all_rows = []
    for sector, sec_tickers in sector_groups.items():
        sector_agg = compute_sector_aggregates(fund_cache, sec_tickers)
        if sector_agg.empty:
            continue
        sec_lookup = {}
        for i in range(len(sector_agg)):
            r = sector_agg.iloc[i]
            sec_lookup[(r["year"], r["fp"])] = {"IS": r["IS"], "RS": r["RS"], "FS": r["FS"]}
        for t in sec_tickers:
            df = fund_cache.get(t)
            if df is None:
                continue
            df = df.copy()
            df["fp_order"] = df["fp"].map({"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4})
            df = df.sort_values(["year", "fp_order"]).reset_index(drop=True)
            q_results = []
            for i in range(len(df)):
                row = df.iloc[i]
                year, fp = row["year"], row["fp"]
                if year < 2020:
                    continue
                s = row.get("Revenue", 0) or 0
                ni = row.get("NetIncome", 0) or 0
                ca = row.get("CurrentAssets", 0) or 0
                cl = row.get("CurrentLiabilities", 0) or 0
                e = s - ni if (s and ni is not None) else 0
                s_prev = s
                for j in range(i - 1, -1, -1):
                    prev = df.iloc[j]
                    if prev["fp"] == fp and prev["year"] < year:
                        s_prev = prev.get("Revenue", 0) or 0
                        break
                ia = calc_ia(s, s_prev)
                ra = calc_ra(s, e) if e > 0 else 1.0
                fa = calc_fa(ca, cl) if cl > 0 else 1.0
                key = (year, fp)
                if key in sec_lookup:
                    is_, rs, fs = sec_lookup[key]["IS"], sec_lookup[key]["RS"], sec_lookup[key]["FS"]
                else:
                    is_ = rs = fs = 1.0
                ki = calc_ki(ia, is_)
                kr = calc_kr(ra, rs)
                kf = calc_kf(fa, fs)
                k = ki * kr * kf
                q_results.append({
                    "ticker": t, "year": year, "fp": fp,
                    "K": round(k, 4), "KI": round(ki, 4), "KR": round(kr, 4), "KF": round(kf, 4),
                    "IA": round(ia, 4), "RA": round(ra, 4), "FA": round(fa, 4),
                    "IS": round(is_, 4), "RS": round(rs, 4), "FS": round(fs, 4),
                })
            if not q_results:
                continue
            pd.DataFrame(q_results).to_csv(f"{DATA_PROCESSED}/{t}_K.csv", index=False)
            all_rows.append({
                "ticker": t, "sector": sector,
                "avg_K": round(sum(r["K"] for r in q_results) / len(q_results), 4),
                "latest_K": q_results[-1]["K"],
                "quarter_count": len(q_results),
            })
    df = pd.DataFrame(all_rows).sort_values("avg_K", ascending=False)
    df.to_csv(f"{DATA_PROCESSED}/all_K_ratings.csv", index=False)
    print(f"K calculation done: {len(df)} tickers. Top: {df.head(5)['ticker'].tolist() if len(df) >= 5 else df['ticker'].tolist()}")
    return df


