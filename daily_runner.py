#!/usr/bin/env python3
"""Daily signals: load cached candidates, check earnings, output buy/sell with BMO/AMC."""
import sys, os, json, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, date, timedelta
import pandas as pd
import yfinance as yf

from src.config import (
    DATA_RAW, DATA_PROCESSED, OUTPUT_DIR,
    BACKTEST_SECTOR_VOL_WEIGHTS,
    BACKTEST_COMMISSION_BUY, BACKTEST_SLIPPAGE,
    BACKTEST_MAX_CONCURRENT_POSITIONS, BACKTEST_MAX_POS_FRAC,
)
from src.earnings_calendar import get_earnings_dates, next_trading_day, prev_trading_day
from src.portfolio import Portfolio

LOG = os.path.join(OUTPUT_DIR, "daily_runner.log")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")
    with open(LOG, "a") as f:
        f.write(f"[{ts}] {msg}\n")

log("=== DAILY RUNNER ===")

# 1. Load cached candidates from overnight pipeline (pass 2 — clean)
candidates_path = f"{DATA_PROCESSED}/filtered_candidates.csv"
if not os.path.exists(candidates_path):
    log("No candidates found — run overnight_pipeline first")
    sys.exit(0)

df_f = pd.read_csv(candidates_path)
candidates = df_f["ticker"].tolist()
log(f"Candidates loaded: {len(candidates)}")

# 2. Load repeat offenders to flag (not exclude — they already excluded from df_f)
repeat_offenders_path = f"{DATA_PROCESSED}/repeat_offenders.json"
repeat_offenders = json.load(open(repeat_offenders_path)) if os.path.exists(repeat_offenders_path) else []
log(f"Repeat offenders tracked: {len(repeat_offenders)}")

# 3. Load sectors
sectors_path = f"{DATA_RAW}/ticker_sectors.json"
sectors = json.load(open(sectors_path)) if os.path.exists(sectors_path) else {}

# 4. Portfolio state
portfolio = Portfolio(initial_capital=1500)
summary = portfolio.summary()

# 5. Check earnings dates for candidates
log("Fetching earnings dates...")
df_earnings = get_earnings_dates(candidates)
# Match backtest: use only confirmed (non-estimated) earnings dates
if "is_estimated" in df_earnings.columns:
    df_earnings = df_earnings[df_earnings["is_estimated"] == False]
today = date.today()
log(f"Today: {today}")

# 6. Determine buy/sell signals
next_day = next_trading_day(today)
prev_day = prev_trading_day(today)

# Narrow down to relevant earnings dates first (avoid iterating all)
df_earnings["_date_str"] = df_earnings["date"].apply(lambda x: str(x)[:10] if pd.notna(x) else "")
mask = df_earnings["_date_str"].isin([str(today), str(next_day), str(prev_day)])
df_rel = df_earnings[mask]
log(f"Relevant earnings: {len(df_rel)} rows ({today}, {prev_day}, {next_day})")

# Batch fetch prices for all relevant tickers
signal_tickers = df_rel["ticker"].unique().tolist()
prices = {}
if signal_tickers:
    batch = yf.download(" ".join(signal_tickers), period="1d", interval="5m", progress=False, auto_adjust=True)
    if not batch.empty and isinstance(batch.columns, pd.MultiIndex):
        for t in signal_tickers:
            try:
                prices[t] = float(batch[("Close", t)].dropna().iloc[-1])
            except:
                pass
    if not prices:
        batch = yf.download(" ".join(signal_tickers), period="5d", progress=False, auto_adjust=True)
        if not batch.empty and isinstance(batch.columns, pd.MultiIndex):
            for t in signal_tickers:
                try:
                    prices[t] = float(batch[("Close", t)].dropna().iloc[-1])
                except:
                    pass

# K values lookup — backtest uses avg_K for sizing
k_map = {}
if "avg_K" in df_f.columns:
    for _, r in df_f.iterrows():
        k_map[r["ticker"]] = float(r["avg_K"])

buys_today = []
buys_tomorrow = []
sells_today = []

# First pass: collect raw signals by date group
raw_signals_today = []
raw_signals_tomorrow = []

for _, row in df_rel.iterrows():
    t = row["ticker"]
    ed_raw = row["date"]
    if isinstance(ed_raw, str):
        ed = datetime.strptime(ed_raw[:10], "%Y-%m-%d").date()
    else:
        ed = ed_raw

    dt = row.get("datetime") if "datetime" in row else None
    is_amc = False
    if pd.notna(dt) and hasattr(dt, "hour"):
        is_amc = dt.hour >= 16
    elif pd.notna(dt) and isinstance(dt, str) and len(dt) >= 19:
        try:
            h = datetime.strptime(dt[:19], "%Y-%m-%d %H:%M:%S").hour
            is_amc = h >= 16
        except:
            pass

    price = prices.get(t)
    if price is None:
        continue
    k_value = k_map.get(t) or 1.0

    # Sell: earnings yesterday
    if ed == prev_day:
        pos = portfolio.find_open(t)
        if pos.get("cost", 0) > 0:
            sells_today.append({"ticker": t, "price": round(price, 2), "buy_price": pos.get("buy_price", 0)})

    base_share = 0.33
    k_mult = min(k_value / 1.1, 3.0) if k_value > 0 else 1.0
    sector = sectors.get(t, "")
    vol_w = BACKTEST_SECTOR_VOL_WEIGHTS.get(sector, 1.0)
    # Apply sector volatility weight, then cap at MAX_POS_FRAC (50%) — backtest-equivalent
    pos_share = min(base_share * k_mult * vol_w, BACKTEST_MAX_POS_FRAC)

    # Buy: earnings today (AMC only) — buy at close today
    if ed == today and is_amc:
        raw_signals_today.append({"ticker": t, "K": k_value, "price": round(price, 2), "pos_share": pos_share})

    # Buy: earnings tomorrow — BMO: buy today, AMC: buy tomorrow
    if ed == next_day:
        if is_amc:
            raw_signals_tomorrow.append({"ticker": t, "K": k_value, "price": round(price, 2), "pos_share": pos_share})
        else:
            raw_signals_today.append({"ticker": t, "K": k_value, "price": round(price, 2), "pos_share": pos_share})

# Second pass: allocate capital with portfolio constraints (backtest-equivalent)
def allocate_signals(signals, total_capital, free_capital, open_positions,
                     max_concurrent=BACKTEST_MAX_CONCURRENT_POSITIONS):
    """Allocate capital to signals sorted by K desc, mirroring src/backtest.py:
      - skip tickers already held (open_positions)
      - max new slots = max_concurrent - len(open_positions)
      - position size base = total_capital (compounding), capped by free_capital
      - shares & cost include commission + slippage
    """
    open_tickers = {p["ticker"] for p in open_positions}
    signals = [s for s in signals if s["ticker"] not in open_tickers]
    signals.sort(key=lambda x: x["K"] or 0, reverse=True)

    max_slots = max_concurrent - len(open_positions)
    if max_slots <= 0:
        return []

    used = 0
    slots = 0
    result = []
    for s in signals:
        if slots >= max_slots:
            break
        avail = free_capital - used
        if avail <= 0:
            break
        eff_mult = 1 + BACKTEST_COMMISSION_BUY + BACKTEST_SLIPPAGE
        target = total_capital * s["pos_share"]
        target = min(target, avail)
        shares = int(target / (s["price"] * eff_mult)) if s["price"] > 0 else 0
        if shares < 1:
            continue
        cost = shares * s["price"] * eff_mult
        if cost > avail:
            continue
        used += cost
        slots += 1
        result.append({"ticker": s["ticker"], "K": s["K"], "price": s["price"],
                       "size": round(cost, 2), "shares": shares})
    return result

total_capital = summary["current_capital"]
free_capital = summary["free_capital"]
open_positions = portfolio.open_positions

# Commit SELLs FIRST (frees capital for BUYs), mirroring backtest day loop
sells_today_unique = []
seen_sell_tickers = set()
for s in sells_today:
    if s["ticker"] in seen_sell_tickers:
        continue
    seen_sell_tickers.add(s["ticker"])
    res = portfolio.close_trade(s["ticker"], s["price"])
    if "pnl" in res:
        log(f"SELL {s['ticker']}: buy={s['buy_price']} → sell={s['price']}  pnl=${res['pnl']:.2f}")
        s["pnl"] = res["pnl"]
        sells_today_unique.append(s)

sells_today = sells_today_unique

# Allocate BUYs at today state (after sells committed)
summary = portfolio.summary()
total_capital = summary["current_capital"]
free_capital = summary["free_capital"]
open_positions = portfolio.open_positions
buys_today = allocate_signals(raw_signals_today, total_capital, free_capital, open_positions)

# Commit BUYs for today (dedup by position already in portfolio)
today_str = str(today)
for b in buys_today:
    existing = portfolio.find_open(b["ticker"])
    if existing.get("cost", 0) > 0 and existing.get("buy_date", "") == today_str:
        log(f"SKIP BUY {b['ticker']} — already opened today")
        continue
    pos = portfolio.commit_buy(b["ticker"], b["K"], b["price"], b["shares"])
    if pos.get("shares", 0) >= 1:
        log(f"BUY {b['ticker']}: {b['shares']} @ ${b['price']:.2f}  cost=${pos['cost']:.0f}")
    else:
        log(f"SKIP BUY {b['ticker']}: {pos.get('note', 'no shares')}")

# Forecast tomorrow's BUYs against post-today state (NOT committed)
summary = portfolio.summary()
total_capital = summary["current_capital"]
free_capital = summary["free_capital"]
open_positions = portfolio.open_positions
buys_tomorrow = allocate_signals(raw_signals_tomorrow, total_capital, free_capital, open_positions)

# 7. Generate report
log(f"Signals: {len(sells_today)} sells, {len(buys_today)} buys (AMC), {len(buys_tomorrow)} buys (tomorrow)")

lines = []
lines.append(f"ISTS Signals — {today}")
lines.append(f"Portfolio: ${summary['current_capital']:,.0f}  Free: ${summary['free_capital']:,.0f}")
if portfolio.open_positions:
    lines.append(f"Open ({len(portfolio.open_positions)}): {', '.join(p['ticker'] for p in portfolio.open_positions)}")
lines.append("-" * 40)

if sells_today:
    lines.append("SELL today at close:")
    for s in sells_today:
        lines.append(f"  {s['ticker']:6s} buy=${s['buy_price']:.2f} → sell=${s['price']:.2f}")
        log(f"SELL {s['ticker']}: buy={s['buy_price']} → sell={s['price']}")

if buys_today:
    lines.append("BUY today at close:")
    for b in buys_today:
        k_str = f"K={b['K']:.2f}" if b['K'] else ""
        lines.append(f"  {b['ticker']:6s} ${b['price']:.2f}  {k_str}")
        log(f"BUY {b['ticker']}: price=${b['price']}")

if buys_tomorrow:
    lines.append("BUY tomorrow at close (AMC earnings):")
    for b in buys_tomorrow:
        k_str = f"K={b['K']:.2f}" if b['K'] else ""
        lines.append(f"  {b['ticker']:6s} ${b['price']:.2f}  {k_str}")
        log(f"BUY {b['ticker']}: AMC earnings {next_day}, buy on {next_day}, price=${b['price']}")

if not sells_today and not buys_today and not buys_tomorrow:
    lines.append("No signals today")

lines.append("-" * 40)

msg = "\n".join(lines)
log("\n" + msg)

# 8. Save signals JSON
signals = {
    "date": str(today),
    "sells": sells_today,
    "buys_today": buys_today,
    "buys_tomorrow": buys_tomorrow,
    "portfolio": summary,
    "repeat_offenders": repeat_offenders,
    "open_positions": portfolio.open_positions,
}
with open(f"{OUTPUT_DIR}/signals.json", "w") as f:
    json.dump(signals, f, indent=2, default=str)
log(f"Signals -> {OUTPUT_DIR}/signals.json")
log("=== DONE ===")
