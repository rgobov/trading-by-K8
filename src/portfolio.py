"""Portfolio state management: track capital, positions, generate signals"""
import json, os
from datetime import datetime, date
from src.config import OUTPUT_DIR, BACKTEST_COMMISSION_BUY, BACKTEST_COMMISSION_SELL, BACKTEST_SLIPPAGE, BACKTEST_MARGIN_RATE, DEFAULT_UNIVERSE, DEFAULT_LEVERAGE

STATE_PATH = os.path.join(OUTPUT_DIR, "portfolio_state.json")

class Portfolio:
    def __init__(self, initial_capital: float = 1500):
        self.state_path = STATE_PATH
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.open_positions: list[dict] = []
        self.completed_trades: list[dict] = []
        self.universe = DEFAULT_UNIVERSE
        self.leverage = DEFAULT_LEVERAGE
        self._load()

    def _load(self):
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                data = json.load(f)
            self.initial_capital = data.get("initial_capital", self.initial_capital)
            self.current_capital = data.get("current_capital", self.initial_capital)
            self.open_positions = data.get("open_positions", [])
            self.completed_trades = data.get("completed_trades", [])
            self.universe = data.get("universe", DEFAULT_UNIVERSE)
            self.leverage = data.get("leverage", DEFAULT_LEVERAGE)
        else:
            self.save()

    def save(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump({
                "initial_capital": self.initial_capital,
                "current_capital": self.current_capital,
                "open_positions": self.open_positions,
                "completed_trades": self.completed_trades,
                "universe": self.universe,
                "leverage": self.leverage,
                "last_update": str(date.today()),
            }, f, indent=2)

    def calc_position(self, ticker: str, k_value: float, buy_price: float,
                      base_share: float = 0.33, k_mult_max: float = 3.0,
                      pos_frac_max: float = 0.50) -> dict:
        """Calculate position size for a trade"""
        k_mult = min(k_value / 1.1, k_mult_max) if k_value > 0 else 1.0
        pos_frac = min(base_share * k_mult, pos_frac_max)
        size = self.current_capital * pos_frac
        shares = int(size / buy_price)
        if shares < 1:
            return {"ticker": ticker, "size": 0, "shares": 0, "note": "insufficient capital"}
        buy_mult = 1 + BACKTEST_COMMISSION_BUY + BACKTEST_SLIPPAGE
        cost = round(shares * buy_price * buy_mult, 2)
        return {
            "ticker": ticker,
            "size": round(size, 2),
            "pos_frac": round(pos_frac * 100, 1),
            "shares": shares,
            "cost": cost,
            "buy_price": round(buy_price, 2),
            "k_value": round(k_value, 2),
        }

    def open_trade(self, ticker: str, k_value: float, buy_price: float,
                   base_share: float = 0.33, pos_frac_max: float = 0.50) -> dict:
        """Open a new position, deduct from capital. Checks free capital."""
        pos = self.calc_position(ticker, k_value, buy_price, base_share, pos_frac_max)
        if pos["shares"] < 1:
            return pos
        free = self.free_capital()
        if pos["cost"] > free:
            pos["shares"] = 0
            pos["note"] = f"need ${pos['cost']:.0f}, free ${free:.0f}"
            return pos
        self.current_capital -= pos["cost"]
        pos["buy_date"] = str(date.today())
        pos["status"] = "open"
        self.open_positions.append(pos)
        self.save()
        return pos

    def commit_buy(self, ticker: str, k_value: float, buy_price: float,
                   shares: int, leverage: float = None) -> dict:
        """Commit an already-sized buy (backtest-equivalent): shares are
        computed outside by the caller using backtest sizing rules; here we
        only record the trade — capital is NEVER reduced at buy (mirrors
        backtest), cost is tracked in open_positions for PnL calculation at sell."""
        if shares < 1:
            return {"ticker": ticker, "note": "no shares", "shares": 0}
        buy_mult = 1 + BACKTEST_COMMISSION_BUY + BACKTEST_SLIPPAGE
        cost = round(shares * buy_price * buy_mult, 2)
        own_cost = cost / (1 + (leverage if leverage is not None else self.leverage))
        free = self.free_capital()
        if own_cost > free:
            return {"ticker": ticker, "note": f"need ${own_cost:.0f} own capital, free ${free:.0f}",
                    "cost": cost, "shares": 0}
        pos = {
            "ticker": ticker,
            "k_value": round(k_value, 2),
            "buy_price": round(buy_price, 2),
            "shares": shares,
            "cost": cost,
            "leverage": leverage if leverage is not None else self.leverage,
            "buy_date": str(date.today()),
            "status": "open",
        }
        self.open_positions.append(pos)
        self.save()
        return pos

    def close_trade(self, ticker: str, sell_price: float) -> dict:
        """Close an open position, add P&L (net of commission & slippage) to capital.
        Mirrors backtest: current_capital is NEVER reduced at buy time (cost is
        tracked in open_positions); at sell we add pnl = proceeds - cost.
        If leverage > 0, margin cost is deducted from PnL."""
        for i, pos in enumerate(self.open_positions):
            if pos["ticker"] == ticker:
                sell_mult = 1 - BACKTEST_COMMISSION_SELL - BACKTEST_SLIPPAGE
                proceeds = round(pos["shares"] * sell_price * sell_mult, 2)
                pnl = round(proceeds - pos["cost"], 2)
                lev = pos.get("leverage", 0)
                if lev > 0:
                    buy_date_str = pos.get("buy_date", str(date.today()))
                    try:
                        bd = datetime.strptime(buy_date_str, "%Y-%m-%d").date() if isinstance(buy_date_str, str) else date.today()
                    except:
                        bd = date.today()
                    hold_days = max((date.today() - bd).days, 1)
                    borrowed = pos["cost"] * (1 - 1 / (1 + lev))
                    margin_cost = borrowed * BACKTEST_MARGIN_RATE * hold_days / 365
                    pnl = round(pnl - margin_cost, 2)
                self.current_capital += pnl
                pos["sell_price"] = round(sell_price, 2)
                pos["sell_date"] = str(date.today())
                pos["pnl"] = pnl
                pos["status"] = "closed"
                self.completed_trades.append(pos)
                self.open_positions.pop(i)
                self.save()
                return pos
        return {"ticker": ticker, "note": "not found in open positions"}

    def find_open(self, ticker: str) -> dict:
        for p in self.open_positions:
            if p["ticker"] == ticker:
                return {"ticker": ticker, "buy_date": p.get("buy_date",""), "buy_price": p.get("buy_price",0), "cost": p.get("cost",0)}
        return {"ticker": ticker, "note": "not found"}

    def free_capital(self) -> float:
        used = sum(p["cost"] / (1 + p.get("leverage", 0)) for p in self.open_positions)
        return self.current_capital - used

    def summary(self) -> dict:
        used = sum(p["cost"] for p in self.open_positions)
        return {
            "initial_capital": self.initial_capital,
            "current_capital": round(self.current_capital, 2),
            "free_capital": round(self.current_capital - used, 2),
            "open_count": len(self.open_positions),
            "total_trades": len(self.completed_trades),
            "pnl_total": round(sum(t.get("pnl", 0) for t in self.completed_trades), 2),
        }

    def display_open(self) -> str:
        if not self.open_positions:
            return ""
        lines = ["Открытые позиции:"]
        for p in self.open_positions:
            lines.append(f"  {p['ticker']:>6s} ${p['cost']:>8.0f} ({p['shares']} шт)")
        return "\n".join(lines)
