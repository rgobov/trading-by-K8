"""Portfolio state management: track capital, positions, generate signals"""
import json, os
from datetime import datetime, date
from src.config import OUTPUT_DIR

STATE_PATH = os.path.join(OUTPUT_DIR, "portfolio_state.json")

class Portfolio:
    def __init__(self, initial_capital: float = 1500):
        self.state_path = STATE_PATH
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.open_positions: list[dict] = []
        self.completed_trades: list[dict] = []
        self._load()

    def _load(self):
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                data = json.load(f)
            self.initial_capital = data.get("initial_capital", self.initial_capital)
            self.current_capital = data.get("current_capital", self.initial_capital)
            self.open_positions = data.get("open_positions", [])
            self.completed_trades = data.get("completed_trades", [])
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
        cost = round(shares * buy_price, 2)
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

    def close_trade(self, ticker: str, sell_price: float) -> dict:
        """Close an open position, add proceeds to capital"""
        for i, pos in enumerate(self.open_positions):
            if pos["ticker"] == ticker:
                proceeds = pos["shares"] * sell_price
                pnl = round(proceeds - pos["cost"], 2)
                self.current_capital += proceeds
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
        used = sum(p["cost"] for p in self.open_positions)
        return self.current_capital

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
