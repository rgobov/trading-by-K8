#!/usr/bin/env python3
"""Daily runner: check earnings dates for today/tomorrow, send signals"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from datetime import datetime, timedelta
from src.config import DATA_PROCESSED, DATA_RAW
from src.earnings_calendar import get_earnings_dates, get_earnings_bounds

def send_telegram(msg: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if token and chat_id:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})

candidates = pd.read_csv(f"{DATA_PROCESSED}/filtered_candidates.csv")
tickers = candidates["ticker"].tolist()

df = get_earnings_dates(tickers)
today = datetime.now().date()
tomorrow = today + timedelta(days=1)

# Trades for today (sell yesterday's buys) and tomorrow (buy)
signals = []
for _, row in df.iterrows():
    ed = row["date"]
    if isinstance(ed, str):
        ed = datetime.strptime(ed[:10], "%Y-%m-%d").date()
    if ed in (today, tomorrow):
        signals.append(row)

if not signals:
    msg = "📊 *Сигналов нет* — сегодня и завтра отчетов у кандидатов нет."
    send_telegram(msg)
    print(msg)
else:
    lines = ["📊 *Сигналы на {:%d.%m.%Y}*".format(today), "━━━━━━━━━━━━━━━━"]
    for s in signals:
        ticker = s["ticker"]
        ed = s["date"]
        surprise = f" (surprise: {s.get('surprise_pct', '?')}%)" if pd.notna(s.get('surprise_pct')) else ""
        lines.append(f"🔵 {ticker} — отчет {ed}{surprise}")
    msg = "\n".join(lines)
    send_telegram(msg)
    print(msg)
