#!/usr/bin/env python3
"""Daily runner: check earnings dates for today/tomorrow, send signals via email"""
import sys, os, smtplib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from datetime import datetime, timedelta
from email.message import EmailMessage
from src.config import DATA_PROCESSED, DATA_RAW, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_TO
from src.earnings_calendar import get_earnings_dates

def send_email(subject: str, body: str):
    host = SMTP_HOST
    port = SMTP_PORT
    user = SMTP_USER
    pwd = SMTP_PASSWORD
    to = EMAIL_TO
    if not all([host, user, pwd, to]):
        print("Email config incomplete, skipping")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.set_content(body)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port) as s:
                s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as s:
                s.starttls()
                s.login(user, pwd)
                s.send_message(msg)
        return True
    except Exception as e:
        print(f"Email send failed: {e}")
        return False

def send_telegram(msg: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if token and chat_id:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})

def notify(msg: str):
    print(msg)
    send_telegram(msg)
    send_email("ISTS Trading Signals", msg)

candidates = pd.read_csv(f"{DATA_PROCESSED}/filtered_candidates.csv")
tickers = candidates["ticker"].tolist()

df = get_earnings_dates(tickers)
today = datetime.now().date()
tomorrow = today + timedelta(days=1)

signals = []
for _, row in df.iterrows():
    ed = row["date"]
    if isinstance(ed, str):
        ed = datetime.strptime(ed[:10], "%Y-%m-%d").date()
    if ed in (today, tomorrow):
        signals.append(row)

if not signals:
    msg = f"ISTS: No earnings today ({today})."
    notify(msg)
else:
    lines = [f"ISTS — Earnings {today}", "=" * 40]
    for s in signals:
        ticker = s["ticker"]
        ed = s["date"]
        surprise = f" (surprise: {s.get('surprise_pct', '?')}%)" if pd.notna(s.get('surprise_pct')) else ""
        lines.append(f"{ticker:>6s} — report {ed}{surprise}")
    msg = "\n".join(lines)
    notify(msg)
