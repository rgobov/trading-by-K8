#!/usr/bin/env python3
"""Daily runner: SEC → K calc → filter candidates → check earnings → send email signals"""
import sys, os, json, smtplib, time
from datetime import datetime, timedelta
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from src.config import (
    DATA_RAW, DATA_PROCESSED, OUTPUT_DIR,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_TO,
    FILTER_EXCLUDE_SECTORS, FILTER_K_THRESHOLD,
)
from src.edgar_parser import get_fundamentals, get_ticker_to_cik
from src.calculator import calc_k_for_ticker
from src.filter import filter_by_k_stability
from src.earnings_calendar import get_earnings_dates

os.makedirs(DATA_RAW, exist_ok=True)
os.makedirs(DATA_PROCESSED, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(f"{OUTPUT_DIR}/daily_runner.log", "a") as f:
        f.write(line + "\n")

def send_email(subject: str, body: str):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, EMAIL_TO]):
        log("Email config incomplete")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    msg.set_content(body)
    import ssl
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as e:
        log(f"Email error: {e}")
        return False

# === 1. Load S&P 500 tickers ===
log("Loading tickers...")
tickers_df = pd.read_csv(f"{DATA_RAW}/sp500_tickers.csv")
all_tickers = tickers_df["ticker"].tolist()
log(f"  {len(all_tickers)} tickers")

# === 2. Get sector info (cached) ===
sectors_path = f"{DATA_RAW}/ticker_sectors.json"
if os.path.exists(sectors_path):
    with open(sectors_path) as f:
        sectors = json.load(f)
else:
    log("  Fetching sectors from yfinance...")
    import yfinance as yf
    sectors = {}
    for t in all_tickers:
        try:
            info = yf.Ticker(t).info
            sectors[t] = info.get("sector", "")
        except:
            sectors[t] = ""
        time.sleep(0.02)
    with open(sectors_path, "w") as f:
        json.dump(sectors, f)
    log(f"  Cached {len(sectors)} sectors")

# === 3. Parse SEC fundamentals (incremental) ===
log("Parsing SEC fundamentals (incremental)...")
need_parse = [t for t in all_tickers if not os.path.exists(f"{DATA_RAW}/{t}_fundamentals.csv")]
if need_parse:
    log(f"  Need to parse: {len(need_parse)}")
    for t in need_parse:
        try:
            df = get_fundamentals(t)
            if not df.empty:
                df.to_csv(f"{DATA_RAW}/{t}_fundamentals.csv", index=False)
        except:
            pass
        time.sleep(0.12)
parsed = len([f for f in os.listdir(DATA_RAW) if f.endswith("_fundamentals.csv")])
log(f"  Parsed: {parsed}/{len(all_tickers)}")

# === 4. Calculate K (incremental) ===
log("Calculating K...")
rows = []
for t in all_tickers:
    path = f"{DATA_RAW}/{t}_fundamentals.csv"
    if not os.path.exists(path):
        continue
    result = calc_k_for_ticker(t)
    if "error" not in result:
        qs = result.get("quarters", [])
        rows.append({"ticker": t, "avg_K": result.get("avg_K", 0),
                     "latest_K": qs[-1]["K"] if qs else 0, "qcount": len(qs)})

df_k = pd.DataFrame(rows).sort_values("avg_K", ascending=False)
df_k.to_csv(f"{DATA_PROCESSED}/all_K_ratings.csv", index=False)
log(f"  {len(df_k)} K ratings")

# === 5. Filter candidates ===
log("Filtering candidates...")
df_f = filter_by_k_stability(df_k, threshold=FILTER_K_THRESHOLD, min_above=2, lookback=3)
df_f["sector"] = df_f["ticker"].map(sectors)
df_f = df_f[~df_f["sector"].isin(FILTER_EXCLUDE_SECTORS)]
df_f = df_f[df_f["sector"].notna() & (df_f["sector"] != "")]
df_f.to_csv(f"{DATA_PROCESSED}/filtered_candidates.csv", index=False)
log(f"  {len(df_f)} candidates")

# === 6. Check earnings dates ===
log("Checking earnings dates...")
candidates = df_f["ticker"].tolist()
df_earnings = get_earnings_dates(candidates)
today = datetime.now().date()
tomorrow = today + timedelta(days=1)

signals_buy = []
signals_sell = []
for _, row in df_earnings.iterrows():
    ed = row["date"]
    if isinstance(ed, str):
        ed = datetime.strptime(ed[:10], "%Y-%m-%d").date()
    if ed == today:
        signals_buy.append(row["ticker"])
    elif ed == tomorrow:
        signals_buy.append(row["ticker"])

if not signals_buy:
    msg = f"ISTS: No earnings today ({today})."
    log(msg)
    send_email("ISTS Trading Signals", msg)
else:
    lines = [f"ISTS Signals — {today}", "=" * 40,
             f"BUY before close ({len(signals_buy)}):", ", ".join(signals_buy),
             "", f"Positions: 33% + K-weight, max 3 concurrent"]
    msg = "\n".join(lines)
    log(msg)
    send_email(f"ISTS: {len(signals_buy)} trades today", msg)

log("Done")
