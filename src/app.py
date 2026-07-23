"""Desktop app for ISTS portfolio tracking"""
import json, os, sys, subprocess, threading
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flet as ft
from datetime import date
from src.config import OUTPUT_DIR
from src.portfolio import Portfolio

STATE_PATH = os.path.join(OUTPUT_DIR, "portfolio_state.json")
SIGNALS_PATH = os.path.join(OUTPUT_DIR, "signals_data.json")

class TrackerApp:
    def __init__(self):
        self.portfolio = Portfolio(initial_capital=1500)
        self.signals = {"candidates": [], "sell_signals": []}
        self.last_check = self._get_check_time()
        self._check_proc = None
        self._check_cancelled = False
        self._load_signals()

    def _load_signals(self):
        if os.path.exists(SIGNALS_PATH):
            with open(SIGNALS_PATH) as f:
                self.signals = json.load(f)

    def _get_check_time(self) -> str:
        if os.path.exists(SIGNALS_PATH):
            ts = os.path.getmtime(SIGNALS_PATH)
            return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
        return "никогда"

    def check_signals(self, page, button_row):
        """Run daily_runner in background, show progress in UI, supports cancel"""
        self._check_cancelled = False

        progress = ft.ProgressRing()
        status_text = ft.Text("Запуск проверки...", size=13, color="grey")
        cancel_btn = ft.ElevatedButton("Отмена", on_click=lambda e: self._cancel_check(),
                                       bgcolor="grey", color="white")

        button_row.controls.clear()
        button_row.controls.append(progress)
        button_row.controls.append(status_text)
        button_row.controls.append(cancel_btn)
        page.update()

        def run():
            try:
                script = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "daily_runner.py"
                )
                self._check_proc = subprocess.Popen(
                    [sys.executable, script],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True,
                )
                for line in iter(self._check_proc.stdout.readline, ""):
                    if not line:
                        break
                    if self._check_cancelled:
                        self._check_proc.kill()
                        break
                    for tag, desc in [
                        ("SEC", "SEC данные..."),
                        ("K ratings", "Расчет K..."),
                        ("Filtering", "Фильтр кандидатов..."),
                        ("earnings", "Поиск отчетов..."),
                        ("Signals HTML", "Генерация сигналов..."),
                        ("Email", "Отправка email..."),
                    ]:
                        if tag.lower() in line.lower():
                            status_text.value = desc
                            page.update()
                            break

                self._check_proc.wait(timeout=120)
                self._check_proc = None

                if self._check_cancelled:
                    self._restore_button(page, button_row)
                    return

                self._load_signals()
                self.last_check = self._get_check_time()

            except subprocess.TimeoutExpired:
                status_text.value = "Тайм-аут, повторите"
                if self._check_proc:
                    self._check_proc.kill()
            except Exception as ex:
                status_text.value = f"Ошибка: {ex}"

            self._restore_button(page, button_row)

        threading.Thread(target=run, daemon=True).start()

    def _cancel_check(self):
        self._check_cancelled = True
        if self._check_proc:
            try:
                self._check_proc.kill()
            except:
                pass

    def _restore_button(self, page, button_row):
        button_row.controls.clear()
        button_row.controls.append(
            ft.ElevatedButton("⟳ Проверить сигналы",
                              on_click=lambda e: self.check_signals(page, button_row),
                              bgcolor="blue", color="white", icon="refresh")
        )
        button_row.controls.append(
            ft.Text(f"Последняя: {self.last_check}", size=12, color="grey")
        )
        page.controls.clear()
        page.controls.extend(self._build_rows(page))
        page.update()

    def _save_portfolio(self):
        self.portfolio.save()

    def refresh(self, page):
        self._load_signals()
        for row in self._build_rows(page):
            yield row

    def _build_rows(self, page):
        """Yield page content rows"""
        s = self.portfolio.summary()
        fmt = "${:,.0f}".format
        fmt2 = "${:,.2f}".format
        pnl = s["pnl_total"]

        # Stats bar
        yield ft.Row([
            ft.Container(ft.Column([
                ft.Text("Портфель", size=12, color="grey"),
                ft.Text(fmt(s["current_capital"]), size=22, weight="bold"),
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

        yield ft.Divider()

        # Open positions
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
                ft.Text("", width=80),
            ])
            for p in self.portfolio.open_positions:
                price_input = ft.TextField(value="", width=100, text_align="right", data=p)
                pnl_text = ft.Text("", color="grey")
                def make_close(pos, inp, pnl_t):
                    def close(e):
                        try:
                            sell_price = float(inp.value)
                        except:
                            return
                        proceeds = sell_price * pos["shares"]
                        pnl = proceeds - pos["cost"]
                        pos["sell_price"] = sell_price
                        pos["sell_date"] = str(date.today())
                        pos["pnl"] = pnl
                        self.portfolio.completed_trades.append(pos)
                        self.portfolio.open_positions.remove(pos)
                        self.portfolio.current_capital += proceeds
                        self.portfolio.save()
                        page.controls.clear()
                        page.controls.extend(self._build_rows(page))
                        page.update()
                    return close
                def make_pnl(inp, pnl_t):
                    def calc(e):
                        try:
                            sp = float(inp.value)
                            pnl = sp * p["shares"] - p["cost"]
                            pnl_t.value = f"{'+' if pnl>=0 else ''}${pnl:,.0f}"
                            pnl_t.color = "green" if pnl >= 0 else "red"
                            page.update()
                        except:
                            pass
                    return calc
                inp = price_input
                pnl_t = pnl_text
                inp.on_change = make_pnl(inp, pnl_t)
                yield ft.Row([
                    ft.Text(p["ticker"], width=80, weight="bold"),
                    ft.Text(f"${p['buy_price']:.2f}", width=80),
                    ft.Text(str(p["shares"]), width=50),
                    ft.Text(f"${p['cost']:,.0f}", width=100),
                    inp,
                    ft.ElevatedButton("Закрыть", on_click=make_close(p, inp, pnl_t), bgcolor="red", color="white"),
                    pnl_t,
                ], vertical_alignment="center")

        yield ft.Divider()

        # BUY signals
        yield ft.Text("🟢 BUY сигналы (сегодня)", size=18, weight="bold")
        cand = self.signals.get("candidates", [])
        if not cand:
            yield ft.Text("Нет сигналов", italic=True, color="grey")
        else:
            for s in cand:
                pos_frac = min(0.33 * min(s.get("k", 1.1) / 1.1, 3.0), 0.50)
                target_size = s.get("size", 0)
                shares = s.get("shares", 0)
                est_price = s.get("price", 0)
                is_open = s.get("is_opened", False)
                # Skip positions already opened
                if is_open:
                    continue
                # Check if already in portfolio
                existing = [p for p in self.portfolio.open_positions if p["ticker"] == s.get("ticker")]
                if existing:
                    continue

                def make_buy(ticker, est_p, pos_frac, port):
                    def buy(e):
                        dlg = ft.AlertDialog(
                            title=ft.Text(f"{ticker} — цена из wikifolio"),
                            content=ft.Column([
                                ft.Text(f"Размер позиции: ${port * pos_frac:,.0f}"),
                                ft.TextField(label="Цена покупки из wikifolio ($)",
                                             value=est_p, width=200),
                            ], tight=True, spacing=10),
                            actions=[
                                ft.TextButton("Отмена", on_click=lambda e: close_dlg(dlg, page)),
                                ft.ElevatedButton("✅ Купить", on_click=lambda e: confirm_buy(e, dlg, ticker, port, pos_frac)),
                            ],
                        )
                        page.dialog = dlg
                        dlg.open = True
                        page.update()
                    return buy

                def confirm_buy(e, dlg, ticker, port, pos_frac):
                    try:
                        wikifolio_price = float(dlg.content.controls[1].value)
                        if wikifolio_price <= 0:
                            raise ValueError
                    except:
                        page.snack_bar = ft.SnackBar(ft.Text("Введи корректную цену"))
                        page.snack_bar.open = True
                        page.update()
                        return
                    target_size = port * pos_frac
                    shares = int(target_size / wikifolio_price)
                    if shares < 1:
                        page.snack_bar = ft.SnackBar(ft.Text("Не хватает даже на 1 акцию"))
                        page.snack_bar.open = True
                        page.update()
                        return
                    cost = shares * wikifolio_price
                    free = self.portfolio.free_capital()
                    if cost > free:
                        page.snack_bar = ft.SnackBar(ft.Text(f"Не хватает: нужно ${cost:,.0f}, свободно ${free:,.0f}"))
                        page.snack_bar.open = True
                        page.update()
                        return
                    self.portfolio.open_positions.append({
                        "ticker": ticker, "buy_price": wikifolio_price,
                        "shares": shares, "cost": cost,
                        "buy_date": str(date.today()), "status": "open",
                        "source": "wikifolio",
                    })
                    self.portfolio.current_capital -= cost
                    self.portfolio.save()
                    dlg.open = False
                    page.dialog = None
                    page.controls.clear()
                    page.controls.extend(self._build_rows(page))
                    page.update()

                def close_dlg(dlg, page):
                    dlg.open = False
                    page.dialog = None
                    page.update()

                action = s.get("action", "")
                is_missed = "пропущен" in action
                is_bmo = not s.get("is_amc", True) and s.get("when") == "сегодня"
                note = s.get("note", "")
                btn_color = "grey" if is_missed else "green"
                btn_text = "⛔ Пропущен" if is_missed else "➕ Купить"
                action_label = action.replace("покупка ", "🟢 ").replace("пропущен", "🔴 пропущен")
                yield ft.Row([
                    ft.Text(s.get("ticker", ""), width=80, weight="bold",
                            color="orange" if is_missed else "green"),
                    ft.Text(f"K={s.get('k',0):.2f}", width=80),
                    ft.Text(f"${target_size:,.0f}" if target_size else "-", width=100),
                    ft.Text(f"≈{shares} шт" if shares else "-", width=70),
                    ft.Text(f"{action_label}{' — '+note if note else ''}",
                           width=220, size=11, color="orange" if is_missed else "grey"),
                    ft.ElevatedButton(btn_text,
                        on_click=make_buy(s.get("ticker",""), est_price, pos_frac,
                                          self.portfolio.current_capital) if not is_missed else None,
                        bgcolor=btn_color, color="white", disabled=is_missed),
                ])

        yield ft.Divider()

        # SELL signals
        yield ft.Text("🔴 SELL сигналы (сегодня)", size=18, weight="bold")
        sells = self.signals.get("sell_signals", [])
        if not sells:
            yield ft.Text("Нет сигналов", italic=True, color="grey")
        else:
            for s in sells:
                yield ft.Row([
                    ft.Text(s.get("ticker", ""), width=80, weight="bold", color="red"),
                    ft.Text(f"Куплен {s.get('buy_date','-')}", width=150),
                    ft.Text(f"${s.get('buy_price',0):.0f}", width=80),
                ])

        yield ft.Divider()

        # History
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

        # Поле портфель + кнопки
        capital_input = ft.TextField(value=str(self.portfolio.current_capital), width=150, text_align="right")
        def update_capital(e):
            try:
                self.portfolio.current_capital = float(capital_input.value)
                self.portfolio.save()
                page.controls.clear()
                page.controls.extend(self._build_rows(page))
                page.update()
            except:
                pass
        def export_state(e):
            self.portfolio.save()
            page.snack_bar = ft.SnackBar(ft.Text(f"Сохранено в {STATE_PATH}"))
            page.snack_bar.open = True
            page.update()
        def reset_tracker(e):
            self.portfolio.open_positions = []
            self.portfolio.completed_trades = []
            self.portfolio.current_capital = self.portfolio.initial_capital
            self.portfolio.save()
            page.controls.clear()
            page.controls.extend(self._build_rows(page))
            page.update()

        yield ft.Divider()
        btn_row = ft.Row([
            ft.ElevatedButton("⟳ Проверить сигналы",
                              on_click=lambda e: self.check_signals(page, btn_row),
                              bgcolor="blue", color="white", icon="refresh"),
            ft.Text(f"Последняя: {self.last_check}", size=12, color="grey"),
        ])
        yield btn_row
        yield ft.Row([
            ft.Text("Портфель: $"),
            capital_input,
            ft.ElevatedButton("Обновить", on_click=update_capital),
            ft.ElevatedButton("💾 Сохранить", on_click=export_state, bgcolor="blue", color="white"),
            ft.ElevatedButton("Сброс", on_click=reset_tracker, bgcolor="red", color="white"),
        ])

def main(page: ft.Page):
    page.title = "ISTS Portfolio Tracker"
    page.theme_mode = ft.ThemeMode.DARK
    page.scroll = ft.ScrollMode.AUTO
    page.padding = 20
    page.window_width = 800
    page.window_height = 700
    page.window_min_width = 600
    page.window_min_height = 400

    app = TrackerApp()
    page.controls.extend(app._build_rows(page))
    page.on_close = lambda e: app._cancel_check()
    page.update()

ft.app(target=main)
