#!/usr/bin/env python3
"""Run daily_runner and email signals to user."""
import sys, os, json, smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, date
from src.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_TO, OUTPUT_DIR

SIGNALS_PATH = os.path.join(OUTPUT_DIR, "signals.json")

def send_email(subject: str, html: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(html, "html", "utf-8"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)

def build_html(signals: dict) -> str:
    today = signals.get("date", str(date.today()))
    portfolio = signals.get("portfolio", {})
    cap = portfolio.get("current_capital", 0)
    free = portfolio.get("free_capital", 0)

    rows_buy = ""
    for key, label in [("buys_today", "🟢 Купить сегодня на закрытии"),
                       ("buys_tomorrow", "🟡 Купить завтра на закрытии")]:
        items = signals.get(key, [])
        if not items:
            continue
        rows_buy += f"<tr><td colspan='4' style='font-weight:bold;padding-top:12px'>{label}</td></tr>"
        for s in items:
            ticker = s.get("ticker", "")
            k = s.get("K", 0)
            price = s.get("price", 0)
            shares = s.get("shares", 0)
            size = s.get("size", 0)
            rows_buy += f"<tr><td>{ticker}</td><td>K={k:.2f}</td><td>${price:.2f}</td><td>{shares} шт (${size:,.0f})</td></tr>"

    rows_sell = ""
    for s in signals.get("sells", []):
        rows_sell += f"<tr><td>{s['ticker']}</td><td>${s.get('buy_price',0):.2f}</td><td>${s.get('price',0):.2f}</td></tr>"

    ro_list = signals.get("repeat_offenders", [])
    ro_text = ", ".join(ro_list) if ro_list else "—"

    html = f"""<html><body style="font-family:Arial,sans-serif;font-size:14px">
<h2>ISTS Signals — {today}</h2>
<p style="color:green">Портфель: ${cap:,.0f} | Свободно: ${free:,.0f}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse">
<tr style="background:#f0f0f0"><th>Тикер</th><th>K</th><th>Цена</th><th>Объём</th></tr>
{rows_buy}
</table>
{f"<h3>SELL</h3><table cellpadding=4><tr><th>Тикер</th><th>Куплено</th><th>Продаётся</th></tr>{rows_sell}</table>" if rows_sell else ""}
<p style="color:#888;font-size:12px">Рецидивисты: {ro_text}</p>
<hr><p style="color:#aaa;font-size:11px">ISTS — Инвестиционно-Спекулятивная Торговая Система</p>
</body></html>"""
    return html

def main():
    if not SMTP_PASSWORD:
        print("SMTP_PASSWORD not set. Create .env file.")
        sys.exit(1)

    # Run daily_runner first to refresh signals
    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_runner.py")
    os.system(f"{sys.executable} {runner} > /dev/null 2>&1")

    subj_prefix = "[ISTS]"
    today = date.today()

    if os.path.exists(SIGNALS_PATH):
        with open(SIGNALS_PATH) as f:
            signals = json.load(f)
    else:
        signals = {}

    sig_date = signals.get("date", "")
    buys_today = signals.get("buys_today", [])
    buys_tomorrow = signals.get("buys_tomorrow", [])
    sells = signals.get("sells", [])

    n_buys = len(buys_today) + len(buys_tomorrow)
    n_sells = len(sells)

    subject = f"{subj_prefix} {sig_date or today} — {n_buys} buy / {n_sells} sell"
    html = build_html(signals)
    send_email(subject, html)
    print(f"Email sent: {subject}")

if __name__ == "__main__":
    main()
