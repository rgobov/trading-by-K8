"""Desktop app for ISTS — кандидаты + сигналы по отчётам + размер позиции"""
import json, os, sys, threading, subprocess
from datetime import datetime, date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flet as ft
import pandas as pd
import yfinance as yf

from src.config import (
    DATA_PROCESSED, OUTPUT_DIR,
    BACKTEST_COMMISSION_BUY, BACKTEST_COMMISSION_SELL,
    BACKTEST_SLIPPAGE, BACKTEST_MAX_POS_FRAC,
    BACKTEST_SECTOR_VOL_WEIGHTS, UNIVERSE_RUSSELL, UNIVERSE_SP500,
)
from src.portfolio import Portfolio
from src.earnings_calendar import get_earnings_dates, next_trading_day, prev_trading_day

PRICE_CACHE_PATH = os.path.join(OUTPUT_DIR, "price_cache.json")
EARNINGS_CACHE_PATH = os.path.join(OUTPUT_DIR, "earnings_cache.json")
UNIVERSES = {
    UNIVERSE_RUSSELL: {"label": "Russell 1000"},
    UNIVERSE_SP500:   {"label": "S&P 500"},
}

class App:
    def __init__(self):
        self.portfolio = Portfolio(initial_capital=1500)
        self.candidates: dict[str, list[dict]] = {}
        self.prices: dict[str, float] = {}
        self.earnings: dict[str, list] = {}
        self.sells_today: list = []
        self.price_stale = True
        self.load_error = ""
        self._pipeline_running = False
        self._pipeline_cancelled = False
        self._pipeline_proc = None
        self._load_candidates_fast()
        self._load_cached_earnings()

    # ── Загрузка кандидатов + цен ──

    def _load_candidates_fast(self):
        try:
            for uname in UNIVERSES:
                cpath = f"{DATA_PROCESSED}/filtered_candidates_{uname}.csv"
                if not os.path.exists(cpath):
                    continue
                df = pd.read_csv(cpath)
                rows = []
                for _, r in df.iterrows():
                    rows.append({
                        "ticker": r["ticker"],
                        "K": r.get("latest_K", r.get("avg_K", 0)),
                        "avg_K": r.get("avg_K", 0),
                        "sector": r.get("sector", ""),
                    })
                self.candidates[uname] = rows
            if os.path.exists(PRICE_CACHE_PATH):
                self.prices = json.load(open(PRICE_CACHE_PATH))
            self._apply_prices()
        except Exception as e:
            self.load_error = str(e)

    def _apply_prices(self):
        for uname in self.candidates:
            for r in self.candidates[uname]:
                r["price"] = self.prices.get(r["ticker"])

    def _refresh_prices(self):
        all_tickers = list(set(
            r["ticker"] for rows in self.candidates.values() for r in rows
        ))
        if not all_tickers:
            return
        try:
            hist = yf.download(" ".join(all_tickers), period="5d", progress=False, auto_adjust=True)
            prices = {}
            if not hist.empty and isinstance(hist.columns, pd.MultiIndex):
                for t in all_tickers:
                    try:
                        prices[t] = round(float(hist[("Close", t)].dropna().iloc[-1]), 2)
                    except:
                        pass
            if prices:
                self.prices.update(prices)
                json.dump(self.prices, open(PRICE_CACHE_PATH, "w"))
                self._apply_prices()
        except Exception as e:
            self.load_error = str(e)
        self.price_stale = False

    # ── Загрузка дат отчётов + сигналы ──

    def _load_cached_earnings(self):
        if os.path.exists(EARNINGS_CACHE_PATH):
            with open(EARNINGS_CACHE_PATH) as f:
                self.earnings = json.load(f)

    def _refresh_earnings(self):
        all_tickers = list(set(
            r["ticker"] for rows in self.candidates.values() for r in rows
        ))
        if not all_tickers:
            return
        try:
            df = get_earnings_dates(all_tickers)
            earnings = {}
            if "is_estimated" in df.columns:
                prev_td = prev_trading_day(date.today())
                df["_rel"] = pd.to_datetime(df["date"], errors="coerce")
                df = df[
                    (df["is_estimated"] == False)
                    | (df["_rel"] >= pd.Timestamp(prev_td))
                ]
            for _, row in df.iterrows():
                t = row["ticker"]
                d = str(row["date"])[:10] if pd.notna(row["date"]) else ""
                dt = str(row.get("datetime", ""))
                is_est = bool(row.get("is_estimated", True))
                if d:
                    earnings.setdefault(t, []).append({"date": d, "datetime": dt, "is_estimated": is_est})
            self.earnings = earnings
            json.dump(self.earnings, open(EARNINGS_CACHE_PATH, "w"))
        except Exception as e:
            self.load_error = str(e)

    def _signal_for(self, ticker: str) -> dict:
        """Сигнал по стратегии: buy T-1, sell T+1 (T=дата отчёта).
        Возвращает {'action': 'buy_today'|'buy_tmr'|'sell'|'missed'|'', 'label': '', 'color': ''}"""
        eds = self.earnings.get(ticker, [])
        if not eds:
            return {"action": "", "label": "", "color": ""}
        today = date.today()
        nxt = next_trading_day(today)
        prv = prev_trading_day(today)
        for ed in eds[:1]:
            try:
                d = datetime.strptime(ed["date"][:10], "%Y-%m-%d").date()
            except:
                continue
            dt_str = ed.get("datetime", "")
            is_amc = True  # default to AMC
            if dt_str and len(dt_str) >= 19:
                try:
                    h = datetime.strptime(dt_str[:19], "%Y-%m-%d %H:%M:%S").hour
                    is_amc = h >= 16
                except:
                    pass
            open_here = any(p["ticker"] == ticker for p in self.portfolio.open_positions)

            # SELL: отчёт был ВЧЕРА (T-1) — продажа сегодня
            if d == prv and open_here:
                return {"action": "sell", "label": "SELL", "color": "red"}

            # BUY: отчёт сегодня AMC → купить сегодня на закрытии
            if d == today and is_amc:
                if open_here:
                    return {"action": "", "label": "в портфеле", "color": "grey"}
                return {"action": "buy_today", "label": "BUY AMC", "color": "green"}

            # MISSED: отчёт сегодня BMO (гэп уже был)
            if d == today and not is_amc:
                if open_here:
                    return {"action": "", "label": "в портфеле", "color": "orange"}
                return {"action": "missed", "label": "BMO TODAY", "color": "orange"}

            # BUY: отчёт ЗАВТРА BMO → купить сегодня
            if d == nxt and not is_amc:
                if not open_here:
                    return {"action": "buy_today", "label": "BUY TMR BMO", "color": "green"}
                return {"action": "", "label": "в портфеле", "color": "grey"}
            # BUY: отчёт ЗАВТРА AMC → купить завтра
            if d == nxt and is_amc:
                if not open_here:
                    return {"action": "buy_tmr", "label": "BUY TMR AMC", "color": "lightgreen"}
                return {"action": "", "label": "в портфеле", "color": "grey"}

            # Отчёт позже — не показываем
            if d > nxt:
                return {"action": "", "label": "", "color": ""}
        return {"action": "", "label": "", "color": ""}

    def _run_pipeline(self, page, status_row):
        self._pipeline_running = True
        self._pipeline_cancelled = False
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "overnight_pipeline.py")
        self._pipeline_proc = subprocess.Popen(
            [sys.executable, script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in iter(self._pipeline_proc.stdout.readline, ""):
            if not line or self._pipeline_cancelled:
                if self._pipeline_cancelled:
                    self._pipeline_proc.kill()
                break
            tag_map = {"SEC": "SEC...", "K ratings": "K...",
                       "Filtering": "Фильтр...", "Pass 1": "Pass 1...",
                       "Pass 2": "Pass 2...", "PIPELINE COMPLETE": "Готово!"}
            for tag, desc in tag_map.items():
                if tag.lower() in line.lower():
                    status_row.controls[1].value = desc
                    page.update()
                    break
        self._pipeline_proc.wait(timeout=7200)
        self._pipeline_proc = None
        self._pipeline_running = False
        self._load_candidates_fast()
        self._refresh_prices()

    def calc_position(self, capital, leverage, K, sector, price):
        if not price or price <= 0:
            return {"shares": 0, "cost": 0, "pos_share": 0}
        k_mult = min(K / 1.1, 3.0) if K > 0 else 1.0
        vol_w = BACKTEST_SECTOR_VOL_WEIGHTS.get(sector, 1.0)
        pos_share = min(0.33 * k_mult * vol_w, BACKTEST_MAX_POS_FRAC)
        lev_mult = 1 + leverage
        target = capital * pos_share * lev_mult
        eff = 1 + BACKTEST_COMMISSION_BUY + BACKTEST_SLIPPAGE
        shares = int(target / (price * eff))
        if shares < 1:
            return {"shares": 0, "cost": 0, "pos_share": pos_share}
        cost = round(shares * price * eff, 2)
        return {"shares": shares, "cost": cost, "pos_share": pos_share}

    # ── BUILD UI ──

    def build(self, page: ft.Page):
        s = self.portfolio.summary()
        fmt = "${:,.0f}".format
        cap = s["current_capital"]
        lev = self.portfolio.leverage
        pnl = s["pnl_total"]

        def rebuild():
            page.controls.clear()
            page.controls.extend(self.build(page))
            page.update()

        def signal_rows():
            """Yield (action, ticker, K, price, shares, cost, label, color, universe, pos_dict)"""
            for uname in UNIVERSES:
                for r in self.candidates.get(uname, []):
                    sig = self._signal_for(r["ticker"])
                    if not sig["action"]:
                        continue
                    pos = self.calc_position(cap, lev, r["K"], r["sector"], r.get("price"))
                    yield (sig["action"], r["ticker"], r["K"], r.get("price"),
                           pos["shares"], pos["cost"], sig["label"], sig["color"], uname, pos)

        # ========== STATS ==========
        yield ft.Row([
            ft.Container(ft.Column([
                ft.Text("Портфель", size=12, color="grey"),
                ft.Text(fmt(cap), size=22, weight="bold"),
            ], spacing=2), expand=1),
            ft.Container(ft.Column([
                ft.Text("Свободно", size=12, color="grey"),
                ft.Text(fmt(s["free_capital"]), size=22, weight="bold", color="green"),
            ], spacing=2), expand=1),
            ft.Container(ft.Column([
                ft.Text("Открыто", size=12, color="grey"),
                ft.Text(str(s["open_count"]), size=22, weight="bold", color="orange"),
            ], spacing=2), expand=1),
            ft.Container(ft.Column([
                ft.Text("PNL", size=12, color="grey"),
                ft.Text(fmt(abs(pnl)), size=22, weight="bold",
                        color="green" if pnl >= 0 else "red"),
            ], spacing=2), expand=1),
        ])

        # ========== CONTROLS ==========
        cap_input = ft.TextField(value=str(int(cap)), width=130, text_align="right")
        lev_text = ft.Text(f"{lev*100:.0f}%", size=16, weight="bold", width=50)

        def on_capital(e):
            try:
                self.portfolio.current_capital = float(cap_input.value)
                self.portfolio.save()
                rebuild()
            except: pass
        def on_leverage(e):
            pct = round(e.control.value)
            lev_text.value = f"{pct}%"
            page.update()
            self.portfolio.leverage = pct / 100
            self.portfolio.save()
            rebuild()
        def on_refresh(e):
            self.price_stale = True
            rebuild()
            def run():
                self._refresh_prices()
                self._refresh_earnings()
                rebuild()
            threading.Thread(target=run, daemon=True).start()

        yield ft.Row([
            ft.Container(ft.Row([
                ft.Text("Капитал: $", size=14), cap_input,
                ft.Button("OK", on_click=on_capital),
            ]), expand=1),
            ft.Container(ft.Row([
                ft.Text("Плечо:", size=14),
                ft.Slider(value=lev*100, min=0, max=100, divisions=20,
                         label="{value}%", width=160, on_change=on_leverage),
                lev_text,
            ]), expand=2),
            ft.Button("⟳ Обновить", icon="refresh", bgcolor="blue", color="white",
                      on_click=on_refresh),
        ])

        yield ft.Divider(height=5)

        if not self.candidates:
            yield ft.Row([ft.ProgressRing(), ft.Text("Нет кандидатов — нажми ⟳ Pipeline", size=14, color="grey")])
            return
        if self.load_error:
            yield ft.Text(f"Ошибка: {self.load_error}", color="red")
            return
        if self.price_stale:
            yield ft.Row([ft.ProgressRing(width=16, height=16), ft.Text("Обновление цен...", size=12, color="grey")])

        # ========== ПОРТФЕЛЬ (кратко) ==========
        if self.portfolio.open_positions:
            held = ', '.join(f"{p['ticker']} (${p['cost']:,.0f})" for p in self.portfolio.open_positions)
            yield ft.Container(
                ft.Row([ft.Text("📂 В портфеле:", weight="bold", size=14), ft.Text(held, size=14)]),
                bgcolor="#33222288", padding=8, border_radius=5
            )
            yield ft.Divider(height=5)

        # ========== SIGNALS ==========
        signals = list(signal_rows())
        sells = [s for s in signals if s[0] == "sell"]
        buys_today = [s for s in signals if s[0] == "buy_today"]
        buys_tmr = [s for s in signals if s[0] == "buy_tmr"]
        missed = [s for s in signals if s[0] == "missed"]

        # --- SELL ---
        if sells:
            yield ft.Text("🔴 ПРОДАТЬ СЕГОДНЯ", size=18, weight="bold", color="red")
            for s_data in sells:
                _, t, k, price, shares, cost, label, color, uname, pos_dict = s_data
                yield ft.Container(ft.Row([
                    ft.Text(t, width=80, weight="bold"),
                    ft.Text(f"K={k:.2f}", width=65, size=12),
                    ft.Text(f"${price:.2f}" if price else "-", width=70),
                    ft.Text(f"{shares} шт", width=55),
                    ft.Text(f"${cost:,.0f}" if cost else "-", width=90),
                    ft.Text(uname[:6], width=60, size=11, color="grey"),
                ]), bgcolor="#33ff0000", padding=5, border_radius=5)
            yield ft.Divider(height=5)
        elif not buys_today and not buys_tmr:
            yield ft.Text("Нет сигналов на сегодня/завтра", italic=True, color="grey")

        # --- BUY TODAY ---
        if buys_today:
            yield ft.Text(f"🟢 КУПИТЬ СЕГОДНЯ ({len(buys_today)})", size=18, weight="bold", color="green")
            for s_data in buys_today:
                _, t, k, price, shares, cost, label, color, uname, pos_dict = s_data
                def make_buy(tkr, k_val, pr, sh, cst):
                    def buy(e):
                        r = self.portfolio.commit_buy(tkr, k_val, pr, sh, lev)
                        rebuild()
                    return buy
                yield ft.Container(ft.Row([
                    ft.Text(t, width=80, weight="bold", color="green"),
                    ft.Text(f"K={k:.2f}", width=65, size=12),
                    ft.Text(f"${price:.2f}" if price else "-", width=70),
                    ft.Text(f"{shares} шт", width=55),
                    ft.Text(f"${cost:,.0f}" if cost else "-", width=90),
                    ft.Text(uname[:6], width=60, size=11, color="grey"),
                    ft.Button("➕ Купить", on_click=make_buy(t, k, price, shares, cost),
                              bgcolor="green", color="white"),
                ]), bgcolor="#3300ff00", padding=5, border_radius=5)
            yield ft.Divider(height=5)

        # --- BUY TOMORROW ---
        if buys_tmr:
            yield ft.Text(f"🟡 КУПИТЬ ЗАВТРА ({len(buys_tmr)})", size=18, weight="bold", color="yellow")
            for s_data in buys_tmr:
                _, t, k, price, shares, cost, label, color, uname, pos_dict = s_data
                yield ft.Container(ft.Row([
                    ft.Text(t, width=80, weight="bold"),
                    ft.Text(f"K={k:.2f}", width=70, size=12),
                    ft.Text(f"${price:.2f}" if price else "-", width=80),
                    ft.Text(f"{shares} шт", width=60),
                    ft.Text(f"${cost:,.0f}" if cost else "-", width=100),
                    ft.Text(uname[:8], width=80, size=11, color="grey"),
                ]), bgcolor="#33ffff00", padding=5, border_radius=5)
            yield ft.Divider(height=5)

        # --- MISSED ---
        if missed:
            yield ft.Text(f"🔸 ПРОПУЩЕНО (BMO)", size=14, weight="bold", color="orange")
            for s_data in missed:
                _, t, k, price, shares, cost, label, color, uname, pos_dict = s_data
                yield ft.Row([
                    ft.Text(t, width=80, weight="bold"),
                    ft.Text(f"K={k:.2f}", width=70, size=12),
                    ft.Text(f"${price:.2f}" if price else "-", width=80),
                    ft.Text(uname[:8], width=80, size=11, color="grey"),
                    ft.Text(label, size=11, color="orange"),
                ])
            yield ft.Divider(height=5)

        # ========== OPEN POSITIONS ==========
        yield ft.Text("🟡 Открытые позиции", size=16, weight="bold")
        if not self.portfolio.open_positions:
            yield ft.Text("Нет открытых позиций", italic=True, color="grey")
        else:
            yield ft.Row([
                ft.Text("Тикер", weight="bold", width=70),
                ft.Text("Куплено", weight="bold", width=80),
                ft.Text("Шт", weight="bold", width=40),
                ft.Text("Стоимость", weight="bold", width=80),
                ft.Text("Цена закр.", weight="bold", width=90),
            ])
            for p in self.portfolio.open_positions:
                inp = ft.TextField(value="", width=80, text_align="right")
                pnl_t = ft.Text("", color="grey")
                def make_close(pos, i, pt):
                    def close(e):
                        try: sp = float(i.value)
                        except: return
                        r = self.portfolio.close_trade(pos["ticker"], sp)
                        if "note" in r and "pnl" not in r:
                            page.snack_bar = ft.SnackBar(ft.Text(f"Не найдено: {r['note']}"))
                            page.snack_bar.open = True; page.update()
                            return
                        rebuild()
                    return close
                def make_pnl(i, pt):
                    def calc(e):
                        try:
                            sp = float(i.value)
                            sm = 1 - BACKTEST_COMMISSION_SELL - BACKTEST_SLIPPAGE
                            pnl = sp * p["shares"] * sm - p["cost"]
                            pt.value = f"{'+' if pnl>=0 else ''}${pnl:,.0f}"
                            pt.color = "green" if pnl >= 0 else "red"
                            page.update()
                        except: pass
                    return calc
                inp.on_change = make_pnl(inp, pnl_t)
                yield ft.Row([
                    ft.Text(p["ticker"], width=70, weight="bold"),
                    ft.Text(f"${p['buy_price']:.2f}", width=80),
                    ft.Text(str(p["shares"]), width=40),
                    ft.Text(f"${p['cost']:,.0f}", width=80),
                    inp,
                    ft.Button("Закрыть", on_click=make_close(p, inp, pnl_t),
                              bgcolor="red", color="white"),
                    pnl_t,
                ], vertical_alignment="center")

        yield ft.Divider(height=5)

        # ========== HISTORY ==========
        yield ft.Text("📜 История", size=16, weight="bold")
        if not self.portfolio.completed_trades:
            yield ft.Text("Нет закрытых сделок", italic=True, color="grey")
        else:
            for h in self.portfolio.completed_trades[-15:]:
                pnl = h.get("pnl", 0)
                yield ft.Row([
                    ft.Text(h["ticker"], width=70),
                    ft.Text(h.get("sell_date", "-"), width=90, size=12),
                    ft.Text(f"{'+' if pnl>=0 else ''}${pnl:,.0f}", width=100,
                            color="green" if pnl >= 0 else "red"),
                ])

        yield ft.Divider(height=5)

        # ========== CANDIDATE LIST (collapsible) ==========
        show_candidates = ft.Ref[ft.Column]()
        toggle_btn = ft.Ref[ft.Button]()

        def toggle_candidates(e):
            c = show_candidates.current
            if c is None: return
            c.visible = not c.visible
            e.control.text = "▶ Кандидаты" if not c.visible else "▼ Кандидаты"
            page.update()

        cand_rows = []
        for uname, spec in UNIVERSES.items():
            rows = self.candidates.get(uname, [])
            rows.sort(key=lambda r: r["K"], reverse=True)
            cand_rows.append(ft.Text(f"{spec['label']} ({len(rows)}):", size=13, weight="bold"))
            for r in rows:
                sig = self._signal_for(r["ticker"])
                label = sig["label"] if sig["label"] else ""
                cand_rows.append(ft.Row([
                    ft.Text(r["ticker"], width=70, size=11),
                    ft.Text(f"K={r['K']:.2f}", width=65, size=10),
                    ft.Text(r.get("sector","")[:12], width=90, size=10),
                    ft.Text(label, width=100, size=10, color=sig.get("color","grey")),
                ], vertical_alignment="center", spacing=2))
            cand_rows.append(ft.Divider(height=2))

        total_cand = sum(len(self.candidates.get(u, [])) for u in UNIVERSES)
        yield ft.Row([
            ft.Button(f"▶ Все кандидаты ({total_cand})", ref=toggle_btn,
                      on_click=toggle_candidates, bgcolor="grey", color="white", icon="list"),
        ])
        yield ft.Column(ref=show_candidates, controls=cand_rows, visible=False)

        yield ft.Divider(height=5)

        # ========== BOTTOM BUTTONS ==========
        def export_state(e):
            self.portfolio.save()
            page.snack_bar = ft.SnackBar(ft.Text("Сохранено"))
            page.snack_bar.open = True; page.update()
        def reset_tracker(e):
            self.portfolio.open_positions = []
            self.portfolio.completed_trades = []
            self.portfolio.current_capital = self.portfolio.initial_capital
            self.portfolio.save()
            rebuild()

        pipeline_progress = ft.ProgressRing(visible=False)
        pipeline_status = ft.Text("", size=12, color="grey")
        pipeline_btn = ft.Button("⟳ Pipeline", bgcolor="green", color="white", icon="rocket_launch")
        def cancel_pipeline(e=None):
            self._pipeline_cancelled = True
            if self._pipeline_proc: self._pipeline_proc.kill()
        def on_pipeline(e):
            if self._pipeline_running:
                cancel_pipeline(); return
            pipeline_progress.visible = True
            pipeline_status.value = "Запуск..."
            pipeline_btn.text = "⏹ Стоп"
            pipeline_btn.bgcolor = "grey"
            page.update()
            def run():
                try: self._run_pipeline(page, ft.Row([pipeline_progress, pipeline_status]))
                except Exception as ex: pipeline_status.value = f"Ошибка: {ex}"
                pipeline_progress.visible = False
                pipeline_btn.text = "⟳ Pipeline"
                pipeline_btn.bgcolor = "green"
                pipeline_status.value = "Готово" if not self._pipeline_cancelled else "Отменён"
                rebuild()
            threading.Thread(target=run, daemon=True).start()
        pipeline_btn.on_click = on_pipeline

        yield ft.Row([
            pipeline_progress, pipeline_status, pipeline_btn,
            ft.Button("💾 Сохранить", on_click=export_state, bgcolor="blue", color="white"),
            ft.Button("Сброс", on_click=reset_tracker, bgcolor="red", color="white"),
        ])

def main(page: ft.Page):
    page.title = "ISTS — Кандидаты + сигналы по отчётам"
    page.theme_mode = ft.ThemeMode.DARK
    page.scroll = ft.ScrollMode.AUTO
    page.padding = 20
    page.window_width = 1100
    page.window_height = 850

    app = App()
    page.controls.extend(app.build(page))
    page.update()

    if app.price_stale:
        def refresh():
            app._refresh_prices()
            app._refresh_earnings()
            page.controls.clear()
            page.controls.extend(app.build(page))
            page.update()
        threading.Thread(target=refresh, daemon=True).start()

ft.run(main)
