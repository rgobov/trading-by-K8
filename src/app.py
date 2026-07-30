"""Desktop app for ISTS — показывает кандидатов обеих вселенных с размером позиции"""
import json, os, sys, threading, subprocess
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

PRICE_CACHE_PATH = os.path.join(OUTPUT_DIR, "price_cache.json")
UNIVERSES = {
    UNIVERSE_RUSSELL: {"label": "Russell 1000"},
    UNIVERSE_SP500:   {"label": "S&P 500"},
}

class App:
    def __init__(self):
        self.portfolio = Portfolio(initial_capital=1500)
        self.candidates: dict[str, list[dict]] = {}
        self.prices: dict[str, float] = {}
        self.price_stale = True
        self.load_error = ""
        self._pipeline_running = False
        self._pipeline_cancelled = False
        self._pipeline_proc = None
        self._load_candidates_fast()

    def _load_candidates_fast(self):
        """Load candidates from CSVs + cached prices (fast, no yfinance)."""
        try:
            all_tickers = []
            for uname, spec in UNIVERSES.items():
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
                all_tickers.extend(r["ticker"] for r in rows)

            # Load cached prices
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
        """Download fresh prices from yfinance in background."""
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
            if not line:
                break
            if self._pipeline_cancelled:
                self._pipeline_proc.kill()
                break
            tag_map = {"SEC": "SEC данные...", "K ratings": "Расчет K...",
                       "Filtering": "Фильтр...", "Pass 1": "Бэктест pass 1...",
                       "Pass 2": "Бэктест pass 2...", "PIPELINE COMPLETE": "Готово!"}
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

    def calc_position(self, capital: float, leverage: float, K: float, sector: str, price: float) -> dict:
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

    def build(self, page: ft.Page):
        s = self.portfolio.summary()
        fmt = "${:,.0f}".format
        cap = s["current_capital"]
        lev = self.portfolio.leverage
        pnl = s["pnl_total"]

        # === Stats bar ===
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

        # === Capital + Leverage controls ===
        cap_input = ft.TextField(value=str(int(cap)), width=140, text_align="right")
        lev_text = ft.Text(f"{lev*100:.0f}%", size=16, weight="bold", width=50)
        refresh_btn = ft.Button("⟳ Обновить цены", icon="refresh",
                                         bgcolor="blue", color="white")

        def rebuild():
            page.controls.clear()
            page.controls.extend(self.build(page))
            page.update()

        def on_capital_change(e):
            try:
                self.portfolio.current_capital = float(cap_input.value)
                self.portfolio.save()
                rebuild()
            except:
                pass

        def on_leverage_change(e):
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
                rebuild()
            threading.Thread(target=run, daemon=True).start()

        cap_btn = ft.Button("Применить", on_click=on_capital_change)
        yield ft.Row([
            ft.Container(ft.Row([
                ft.Text("Капитал: $", size=14),
                cap_input,
                cap_btn,
            ]), expand=1),
            ft.Container(ft.Row([
                ft.Text("Плечо:", size=14),
                ft.Slider(value=lev*100, min=0, max=100, divisions=20,
                         label="{value}%", width=180, on_change=on_leverage_change),
                lev_text,
            ]), expand=2),
            refresh_btn,
        ])

        yield ft.Divider()

        # === Loading / Error ===
        if not self.candidates:
            yield ft.Row([ft.ProgressRing(), ft.Text("Нет кандидатов — нажми ⟳ Pipeline", size=14, color="grey")])
            return
        if self.load_error:
            yield ft.Text(f"Ошибка: {self.load_error}", color="red")
            return
        if self.price_stale:
            yield ft.Row([ft.ProgressRing(width=16, height=16), ft.Text("Обновление цен...", size=12, color="grey")])

        # === Universe tabs ===
        tab_labels = []
        tab_contents = []
        for uname, spec in UNIVERSES.items():
            rows = self.candidates.get(uname, [])
            tab_labels.append(ft.Tab(label=f"{spec['label']} ({len(rows)})"))
            if not rows:
                tab_contents.append(ft.Text("Нет кандидатов", italic=True, color="grey"))
                continue

            rows.sort(key=lambda r: r["K"], reverse=True)

            header = ft.Row([
                ft.Text("#", weight="bold", width=30),
                ft.Text("Тикер", weight="bold", width=80),
                ft.Text("K", weight="bold", width=60),
                ft.Text("Сектор", weight="bold", width=120),
                ft.Text("Цена", weight="bold", width=80),
                ft.Text("Доля", weight="bold", width=60),
                ft.Text("Шт", weight="bold", width=60),
                ft.Text("Стоимость", weight="bold", width=100),
            ], vertical_alignment="center")

            items = [header]
            for i, r in enumerate(rows):
                pos = self.calc_position(cap, lev, r["K"], r["sector"], r.get("price"))
                items.append(ft.Row([
                    ft.Text(str(i+1), width=30, color="grey"),
                    ft.Text(r["ticker"], width=80, weight="bold"),
                    ft.Text(f"{r['K']:.2f}", width=60),
                    ft.Text(r.get("sector","")[:18], width=120, size=11),
                    ft.Text(f"${r.get('price',0):.2f}" if r.get("price") else "-", width=80),
                    ft.Text(f"{pos['pos_share']*100:.0f}%", width=60),
                    ft.Text(str(pos["shares"]) if pos["shares"] else "-", width=60),
                    ft.Text(f"${pos['cost']:,.0f}" if pos["cost"] else "-", width=100),
                ], vertical_alignment="center"))

            tab_contents.append(ft.Column(items, scroll=ft.ScrollMode.AUTO, height=400))

        if tab_labels:
            yield ft.Tabs(
                length=len(tab_labels),
                content=ft.Column([
                    ft.TabBar(tabs=tab_labels),
                    ft.TabBarView(controls=tab_contents, expand=True),
                ]),
            )

        yield ft.Divider()

        # === Open positions ===
        yield ft.Text("🟡 Открытые позиции", size=18, weight="bold")
        if not self.portfolio.open_positions:
            yield ft.Text("Нет открытых позиций", italic=True, color="grey")
        else:
            yield ft.Row([
                ft.Text("Тикер", weight="bold", width=80),
                ft.Text("Цена", weight="bold", width=80),
                ft.Text("Шт", weight="bold", width=50),
                ft.Text("Стоимость", weight="bold", width=100),
                ft.Text("Цена закрытия", weight="bold", width=130),
            ])
            for p in self.portfolio.open_positions:
                price_input = ft.TextField(value="", width=100, text_align="right")
                pnl_text = ft.Text("", color="grey")
                def make_close(pos, inp, pnl_t):
                    def close(e):
                        try:
                            sp = float(inp.value)
                        except:
                            return
                        r = self.portfolio.close_trade(pos["ticker"], sp)
                        if "note" in r and "pnl" not in r:
                            page.snack_bar = ft.SnackBar(ft.Text(f"Не найдено: {r['note']}"))
                            page.snack_bar.open = True
                            page.update()
                            return
                        rebuild()
                    return close
                def make_pnl(inp, pnl_t):
                    def calc(e):
                        try:
                            sp = float(inp.value)
                            sm = 1 - BACKTEST_COMMISSION_SELL - BACKTEST_SLIPPAGE
                            pnl = sp * p["shares"] * sm - p["cost"]
                            pnl_t.value = f"{'+' if pnl>=0 else ''}${pnl:,.0f}"
                            pnl_t.color = "green" if pnl >= 0 else "red"
                            page.update()
                        except:
                            pass
                    return calc
                price_input.on_change = make_pnl(price_input, pnl_text)
                yield ft.Row([
                    ft.Text(p["ticker"], width=80, weight="bold"),
                    ft.Text(f"${p['buy_price']:.2f}", width=80),
                    ft.Text(str(p["shares"]), width=50),
                    ft.Text(f"${p['cost']:,.0f}", width=100),
                    price_input,
                    ft.Button("Закрыть", on_click=make_close(p, price_input, pnl_text),
                                      bgcolor="red", color="white"),
                    pnl_text,
                ], vertical_alignment="center")

        yield ft.Divider()

        # === History ===
        yield ft.Text("📜 История (последние 20)", size=18, weight="bold")
        if not self.portfolio.completed_trades:
            yield ft.Text("Нет закрытых сделок", italic=True, color="grey")
        else:
            yield ft.Row([
                ft.Text("Тикер", weight="bold", width=80),
                ft.Text("Дата", weight="bold", width=90),
                ft.Text("PNL", weight="bold", width=100),
            ])
            for h in self.portfolio.completed_trades[-20:]:
                pnl = h.get("pnl", 0)
                yield ft.Row([
                    ft.Text(h["ticker"], width=80),
                    ft.Text(h.get("sell_date", "-"), width=90),
                    ft.Text(f"{'+' if pnl>=0 else ''}${pnl:,.0f}", width=100,
                            color="green" if pnl >= 0 else "red"),
                ])

        # === Bottom buttons ===
        def export_state(e):
            self.portfolio.save()
            page.snack_bar = ft.SnackBar(ft.Text(f"Сохранено в {OUTPUT_DIR}/portfolio_state.json"))
            page.snack_bar.open = True
            page.update()
        def reset_tracker(e):
            self.portfolio.open_positions = []
            self.portfolio.completed_trades = []
            self.portfolio.current_capital = self.portfolio.initial_capital
            self.portfolio.save()
            rebuild()

        pipeline_progress = ft.ProgressRing(visible=False)
        pipeline_status = ft.Text("", size=12, color="grey")
        pipeline_btn = ft.Button("⟳ Pipeline", bgcolor="green", color="white",
                                          icon="rocket_launch")

        def cancel_pipeline(e=None):
            self._pipeline_cancelled = True
            if self._pipeline_proc:
                try: self._pipeline_proc.kill()
                except: pass

        def on_pipeline(e):
            if self._pipeline_running:
                cancel_pipeline()
                return
            pipeline_progress.visible = True
            pipeline_status.value = "Запуск..."
            pipeline_btn.text = "⏹ Стоп"
            pipeline_btn.bgcolor = "grey"
            page.update()
            def run():
                try:
                    self._run_pipeline(page, ft.Row([pipeline_progress, pipeline_status]))
                except Exception as ex:
                    pipeline_status.value = f"Ошибка: {ex}"
                pipeline_progress.visible = False
                pipeline_btn.text = "⟳ Pipeline"
                pipeline_btn.bgcolor = "green"
                pipeline_status.value = f"Готово ({pd.Timestamp.now().strftime('%H:%M')})" if not self._pipeline_cancelled else "Отменён"
                rebuild()
            threading.Thread(target=run, daemon=True).start()

        pipeline_btn.on_click = on_pipeline

        yield ft.Divider()
        yield ft.Row([
            pipeline_progress,
            pipeline_status,
            pipeline_btn,
            ft.Button("💾 Сохранить", on_click=export_state, bgcolor="blue", color="white"),
            ft.Button("Сброс", on_click=reset_tracker, bgcolor="red", color="white"),
        ])

def main(page: ft.Page):
    page.title = "ISTS — Кандидаты по вселенным"
    page.theme_mode = ft.ThemeMode.DARK
    page.scroll = ft.ScrollMode.AUTO
    page.padding = 20
    page.window_width = 1000
    page.window_height = 800
    page.window_min_width = 700
    page.window_min_height = 500

    app = App()
    page.controls.extend(app.build(page))
    page.update()

    # Refresh prices in background (async, doesn't block UI)
    if app.price_stale:
        def refresh():
            app._refresh_prices()
            page.controls.clear()
            page.controls.extend(app.build(page))
            page.update()
        threading.Thread(target=refresh, daemon=True).start()

ft.run(main)
