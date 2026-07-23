#!/usr/bin/env python3
"""Daily runner: SEC → K calc → filter → check earnings → portfolio → email + web signals"""
import sys, os, json, smtplib, ssl
from datetime import datetime, timedelta, date
from email.message import EmailMessage
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import (
    DATA_RAW, DATA_PROCESSED, OUTPUT_DIR,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_TO,
    FILTER_EXCLUDE_SECTORS, FILTER_K_THRESHOLD,
)
from src.portfolio import Portfolio
from src.edgar_parser import get_ticker_to_cik

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
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    msg.set_content(body)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
        log("Email sent")
    except Exception as e:
        log(f"Email error: {e}")

def load_sectors() -> dict:
    path = f"{DATA_RAW}/ticker_sectors.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

import pandas as pd
import yfinance as yf
from src.edgar_parser import get_fundamentals
from src.calculator import calc_k_for_ticker
from src.filter import filter_by_k_stability, load_ticker_k
from src.earnings_calendar import get_earnings_dates, get_earnings_bounds

# === 1. Load tickers ===
log("Loading tickers...")
tickers_df = pd.read_csv(f"{DATA_RAW}/sp500_tickers.csv")
all_tickers = tickers_df["ticker"].tolist()
sectors = load_sectors()

# === 2. Parse SEC (incremental) ===
need_parse = [t for t in all_tickers if not os.path.exists(f"{DATA_RAW}/{t}_fundamentals.csv")]
if need_parse:
    log(f"SEC: {len(need_parse)} new tickers")
    for t in need_parse:
        try:
            df = get_fundamentals(t)
            if not df.empty:
                df.to_csv(f"{DATA_RAW}/{t}_fundamentals.csv", index=False)
        except:
            pass

# === 3. Calculate K ===
rows = []
import glob
for f in glob.glob(f"{DATA_RAW}/*_fundamentals.csv"):
    t = os.path.basename(f).replace("_fundamentals.csv", "")
    r = calc_k_for_ticker(t)
    if "error" not in r:
        qs = r.get("quarters", [])
        rows.append({"ticker": t, "avg_K": r.get("avg_K", 0),
                     "latest_K": qs[-1]["K"] if qs else 0, "qcount": len(qs)})

df_k = pd.DataFrame(rows).sort_values("avg_K", ascending=False)
df_k.to_csv(f"{DATA_PROCESSED}/all_K_ratings.csv", index=False)

# === 4. Filter ===
df_f = filter_by_k_stability(df_k, threshold=FILTER_K_THRESHOLD, min_above=2, lookback=3)
df_f["sector"] = df_f["ticker"].map(sectors)
df_f = df_f[~df_f["sector"].isin(FILTER_EXCLUDE_SECTORS)]
df_f = df_f[df_f["sector"].notna() & (df_f["sector"] != "")]
df_f.to_csv(f"{DATA_PROCESSED}/filtered_candidates.csv", index=False)
log(f"Candidates: {len(df_f)}")

# === 5. Check earnings dates ===
candidates = df_f["ticker"].tolist()
df_earnings = get_earnings_dates(candidates)
today = date.today()
tomorrow = today + timedelta(days=1)

buy_signals = []
for _, row in df_earnings.iterrows():
    ed = row["date"]
    if isinstance(ed, str):
        ed = datetime.strptime(ed[:10], "%Y-%m-%d").date()
    dt = pd.to_datetime(row["datetime"]) if "datetime" in row and pd.notna(row.get("datetime")) else None
    is_amc = True
    if dt is not None and hasattr(dt, 'hour'):
        is_amc = dt.hour >= 15
    if ed == today and is_amc:
        buy_signals.append(row["ticker"])
    elif ed == tomorrow:
        buy_signals.append(row["ticker"])

# === 6. Load portfolio ===
portfolio = Portfolio(initial_capital=1500)
summary = portfolio.summary()

# Open buy signals (generate only — purchase via app button)
signals_data = []
max_concurrent = 3
for t in buy_signals:
    # Load K and price FIRST (before any checks)
    k_row = df_k[df_k["ticker"] == t]
    if k_row.empty:
        continue
    k = float(k_row["avg_K"].iloc[0])
    df_price = yf.Ticker(t).history(period="3d")
    if df_price.empty:
        continue
    price = float(df_price["Close"].iloc[-1])

    open_count = len([p for p in portfolio.open_positions])
    capital = portfolio.current_capital
    free = portfolio.free_capital()
    pos_frac = min(0.33 * min(k / 1.1, 3.0), 0.50)
    target_size = capital * pos_frac
    shares = int(min(target_size, free) / price)

    signals_data.append({
        "ticker": t,
        "k": round(k, 2),
        "price": round(price, 2),
        "size": round(target_size, 0),
        "shares": shares,
        "is_opened": False,
        "note": "" if open_count < max_concurrent else "max_concurrent",
    })
    if open_count >= max_concurrent:
        log(f"SIGNAL {t}: K={k:.2f} size=${target_size:,.0f} (LIMIT {max_concurrent} pos)")
    else:
        log(f"SIGNAL {t}: K={k:.2f} size=${target_size:,.0f} {shares}шт")

summary = portfolio.summary()

# === 7. Generate email ===
lines = [f"📊 ISTS Signals — {today}"]
lines.append(f"Портфель: ${summary['current_capital']:,.0f}")
lines.append(f"Свободно: ${summary['free_capital']:,.0f}")
lines.append("─" * 30)
if portfolio.open_positions:
    lines.append("")
    lines.append("🟡 Открыто:")
    for p in portfolio.open_positions:
        lines.append(f"  {p['ticker']} ${p['cost']:,.0f} ({p['shares']} шт)")
if signals_data:
    lines.append("")
    lines.append("🟢 BUY:")
    for s in signals_data:
        if s["shares"] > 0:
            lines.append(f"  {s['ticker']} K={s['k']:.2f}  ${s['size']:,.0f}  ({s['shares']} шт)")
else:
    lines.append("")
    lines.append("Сигналов нет")
lines.append("─" * 30)
msg = "\n".join(lines)
log(msg)
send_email(f"ISTS: {len(signals_data)} trades today" if signals_data else "ISTS: no trades", msg)

# === 8. Save signals data for app + generate html ===
web_data = {
    "candidates": signals_data,
    "open_positions": portfolio.open_positions,
    "sell_signals": [],
    "completed_trades": len(portfolio.completed_trades),
    "pnl_total": summary["pnl_total"],
}

signals_json_path = f"{OUTPUT_DIR}/signals_data.json"
with open(signals_json_path, "w") as f:
    json.dump(web_data, f, indent=2)
log(f"Signals data -> {signals_json_path}")

html_path = f"{OUTPUT_DIR}/signals.html"
with open("templates/signals.html") as f:
    html = f.read()
html = html.replace("const INIT_DATA = JSON.parse(document.getElementById('__DATA__')?.textContent || '{}');",
                    f"const INIT_DATA = {json.dumps(web_data)};")
with open(html_path, "w") as f:
    f.write(html)
log(f"Signals HTML -> {html_path}")
log("Done")
