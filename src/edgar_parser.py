import requests
import pandas as pd
import json
import time
from tqdm import tqdm
from src.config import DATA_RAW

SEC_HEADERS = {
    "User-Agent": "trading-research/1.0 (contact@example.com)",
    "Accept": "application/json",
}
CIK_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

TAG_REVENUE = {"Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomer",
               "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueServicesNet"}
TAG_NETINCOME = {"NetIncomeLoss", "ProfitLoss"}
TAG_CURRENT_ASSETS = {"AssetsCurrent"}
TAG_CURRENT_LIABILITIES = {"LiabilitiesCurrent"}

_cik_cache = None

def get_ticker_to_cik() -> dict[str, int]:
    """Download SEC company tickers JSON -> {ticker: cik}"""
    global _cik_cache
    if _cik_cache:
        return _cik_cache
    resp = requests.get(CIK_URL, headers=SEC_HEADERS, timeout=30)
    data = resp.json()
    mapping = {}
    for entry in data.values():
        ticker = entry.get("ticker", "").upper()
        cik = entry.get("cik_str", 0)
        if ticker and cik:
            mapping[ticker] = cik
    _cik_cache = mapping
    return mapping

def get_company_facts(cik: int) -> dict:
    """Get XBRL facts JSON for a CIK"""
    url = FACTS_URL.format(cik=cik)
    resp = requests.get(url, headers=SEC_HEADERS, timeout=30)
    return resp.json()

def extract_fact_values(facts: dict, tag_set: set[str]) -> list[dict]:
    """Extract values for a given GAAP tag set"""
    results = []
    for tag, data in facts.items():
        if tag not in tag_set:
            continue
        units = data.get("units", {})
        for unit_key, entries in units.items():
            for entry in entries:
                form = entry.get("form", "")
                if not form.startswith("10-"):
                    continue
                if form.endswith("/A"):
                    continue
                val = entry.get("val")
                end = entry.get("end")
                fp = entry.get("fp", "")
                fy = entry.get("fy")
                if val is not None and end:
                    results.append({
                        "tag": tag,
                        "value": val,
                        "end": end,
                        "fp": fp,
                        "form": form,
                        "fy": fy,
                    })
    return results

def select_best_values(values: list[dict], n_latest: int = 8) -> pd.DataFrame:
    """Select best quarterly values (1 per fiscal period)"""
    if not values:
        return pd.DataFrame()
    df = pd.DataFrame(values)
    df = df.sort_values("end", ascending=False)
    seen_ends = set()
    rows = []
    for _, row in df.iterrows():
        end = row["end"][:10]
        if end in seen_ends or not row["value"]:
            continue
        seen_ends.add(end)
        year = int(end[:4])
        rows.append({
            "end": end,
            "fy": row.get("fy", year),
            "fp": row["fp"],
            "value": row["value"],
        })
        if len(rows) >= n_latest:
            break
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values("end").reset_index(drop=True)
    return result

def fundamentals_to_quarters(
    rev: list[dict], ni: list[dict], ca: list[dict], cl: list[dict]
) -> pd.DataFrame:
    """Convert extracted fact values to quarterly rows"""
    df_rev = select_best_values(rev)
    df_ni = select_best_values(ni)
    df_ca = select_best_values(ca)
    df_cl = select_best_values(cl)
    dfs = [d.set_index(["fy", "fp"]) for d in [df_rev, df_ni, df_ca, df_cl] if not d.empty]
    if not dfs:
        return pd.DataFrame()
    merged = dfs[0].join(dfs[1:], how="outer", lsuffix="_rev", rsuffix="_other")
    merged = merged.reset_index()
    result = []
    for _, row in merged.iterrows():
        result.append({
            "year": row.get("fy"),
            "quarter": row.get("fp", "FY"),
            "end_date": row.get("end", ""),
            "Revenue": row.get("value"),
            "NetIncome": row.get("value_ni") or row.get("value") if False else None,
            "CurrentAssets": None,
            "CurrentLiabilities": None,
        })
    return pd.DataFrame(result)

def get_fundamentals(ticker: str) -> pd.DataFrame:
    """Download and parse fundamentals for a single ticker"""
    cik_map = get_ticker_to_cik()
    cik = cik_map.get(ticker.upper())
    if not cik:
        return pd.DataFrame()
    time.sleep(0.15)
    try:
        data = get_company_facts(cik)
        facts = data.get("facts", {}).get("us-gaap", {})
    except Exception as e:
        print(f"  {ticker}: SEC error - {e}")
        return pd.DataFrame()

    rev = extract_fact_values(facts, TAG_REVENUE)
    ni = extract_fact_values(facts, TAG_NETINCOME)
    ca = extract_fact_values(facts, TAG_CURRENT_ASSETS)
    cl = extract_fact_values(facts, TAG_CURRENT_LIABILITIES)

    if not rev or not ni:
        print(f"  {ticker}: missing revenue or net income data")
        return pd.DataFrame()

    df_rev = select_best_values(rev)
    df_ni = select_best_values(ni)
    df_ca = select_best_values(ca)
    df_cl = select_best_values(cl)

    period_cols = ["end", "fy", "fp"]
    merged = df_rev[period_cols + ["value"]].rename(columns={"value": "Revenue"})
    if not df_ni.empty:
        merged = merged.merge(df_ni[period_cols + ["value"]], on=period_cols, how="left", suffixes=("", "_ni"))
        merged = merged.rename(columns={"value": "NetIncome"})
    else:
        merged["NetIncome"] = None
    if not df_ca.empty:
        merged = merged.merge(df_ca[period_cols + ["value"]], on=period_cols, how="left", suffixes=("", "_ca"))
        merged = merged.rename(columns={"value": "CurrentAssets"})
    else:
        merged["CurrentAssets"] = None
    if not df_cl.empty:
        merged = merged.merge(df_cl[period_cols + ["value"]], on=period_cols, how="left", suffixes=("", "_cl"))
        merged = merged.rename(columns={"value": "CurrentLiabilities"})
    else:
        merged["CurrentLiabilities"] = None

    result = merged.rename(columns={"fy": "year", "end": "end_date"}).sort_values("end_date", ascending=False)
    result["ticker"] = ticker
    cols = [c for c in ["ticker", "year", "fp", "end_date", "Revenue", "NetIncome", "CurrentAssets", "CurrentLiabilities"] if c in result.columns]
    result = result[cols]
    return result

def run_for_tickers(tickers: list[str]) -> dict:
    """Parse fundamentals for a list of tickers"""
    print(f"Fetching CIK mapping...")
    cik_map = get_ticker_to_cik()
    print(f"  {len(cik_map)} tickers in SEC CIK database")
    results = {}
    for t in tqdm(tickers, desc="Parsing SEC EDGAR"):
        if t.upper() not in cik_map:
            continue
        df = get_fundamentals(t)
        if not df.empty:
            path = f"{DATA_RAW}/{t}_fundamentals.csv"
            df.to_csv(path, index=False)
            results[t] = len(df)
    print(f"  Parsed {len(results)} tickers")
    return results

if __name__ == "__main__":
    test_tickers = ["AAPL", "MSFT", "NVDA"]
    run_for_tickers(test_tickers)
