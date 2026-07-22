import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional
from src.config import (
    BACKTEST_MAX_DEPOSIT_PER_POSITION,
    BACKTEST_COMMISSION_BUY,
    BACKTEST_COMMISSION_SELL,
    BACKTEST_SLIPPAGE,
    BACKTEST_MAX_POSITION_CAP,
    DATA_PROCESSED,
)
from src.earnings_calendar import get_earnings_dates, get_earnings_bounds
import yfinance as yf

class Backtest:
    def __init__(
        self,
        initial_capital: float = 1_500,
        max_per_position: float = BACKTEST_MAX_DEPOSIT_PER_POSITION,
        k_weighted: bool = True,
        compounding: bool = True,
    ):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.max_per_position = max_per_position
        self.k_weighted = k_weighted
        self.compounding = compounding
        self.trades: list[dict] = []
        self.equity_curve: list[float] = [initial_capital]
        self._price_cache: dict[str, pd.DataFrame] = {}

    def run_for_candidates(self, candidates: pd.DataFrame, years: int = 3) -> 'Backtest':
        """Run backtest for a list of candidate tickers over recent N years"""
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=years * 365)
        all_tickers = candidates["ticker"].tolist()

        # Batch download all price data at once
        print(f"  Batch downloading price data for {len(all_tickers)} tickers ({years}yr)...")
        buf_days = max(years * 365 + 30, 400)
        hist = yf.download(
            all_tickers,
            start=end_date - timedelta(days=buf_days),
            end=end_date,
            progress=False,
            auto_adjust=True,
        )
        if not hist.empty:
            if isinstance(hist.columns, pd.MultiIndex):
                for t in all_tickers:
                    try:
                        self._price_cache[t] = hist.xs(t, level=1, axis=1)
                    except Exception:
                        pass
            else:
                single = all_tickers[0] if all_tickers else None
                if single:
                    self._price_cache[single] = hist
        print(f"  Cached {len(self._price_cache)} tickers")

        df_earnings = get_earnings_dates(all_tickers)

        for _, cand in candidates.iterrows():
            ticker = cand["ticker"]
            ticker_earnings = df_earnings[df_earnings["ticker"] == ticker]
            for _, ear in ticker_earnings.iterrows():
                earnings_date = ear["date"]
                if pd.isna(earnings_date):
                    continue
                if hasattr(earnings_date, 'date'):
                    earnings_date = earnings_date.date()
                if hasattr(earnings_date, 'to_pydatetime'):
                    earnings_date = earnings_date.to_pydatetime().date()

                earnings_dt = ear.get("datetime", earnings_date)

                buy_date, sell_date = get_earnings_bounds(earnings_date, earnings_dt)

                if buy_date < start_date or sell_date > end_date:
                    continue
                self._simulate_trade(
                    ticker=ticker,
                    buy_date=buy_date,
                    sell_date=sell_date,
                    earnings_date=earnings_date,
                    k_value=cand.get("avg_K", 1.0),
                )
        self._summarize()
        return self

    def _simulate_trade(
        self,
        ticker: str,
        buy_date: datetime,
        sell_date: datetime,
        earnings_date: datetime,
        k_value: float = 1.0,
    ):
        """Simulate single trade: buy at Close of buy_date, sell at Close of sell_date. Position sized by K."""
        try:
            buy_price, sell_price = self._get_prices(ticker, buy_date, sell_date)
        except Exception:
            return
        if buy_price is None or sell_price is None or buy_price <= 0:
            return

        if self.k_weighted and k_value > 0:
            k_mult = min(k_value / 1.1, 3.0)
            pos_frac = self.max_per_position * k_mult
        else:
            pos_frac = self.max_per_position
        pos_frac = min(pos_frac, 0.5)

        # Synchronize trade filtering: use initial capital to determine if 1 share is affordable
        if buy_price is None or np.isnan(buy_price):
            return
        min_shares = int(self.initial_capital * pos_frac / buy_price)
        if min_shares < 1:
            return

        base_capital = self.capital if self.compounding else self.initial_capital
        position_size = base_capital * pos_frac

        # Cap position: never exceed N * initial_capital * max_per_position
        max_pos = self.initial_capital * pos_frac * BACKTEST_MAX_POSITION_CAP
        position_size = min(position_size, max_pos)

        shares = int(position_size / buy_price)
        if shares < 1:
            return
        cost = shares * buy_price
        cost += cost * BACKTEST_COMMISSION_BUY
        cost += shares * buy_price * BACKTEST_SLIPPAGE  # slippage on entry
        proceeds = shares * sell_price
        proceeds -= proceeds * BACKTEST_COMMISSION_SELL
        proceeds -= shares * sell_price * BACKTEST_SLIPPAGE  # slippage on exit
        pnl = proceeds - cost
        pnl_pct = (proceeds / cost - 1) * 100
        self.capital += pnl
        self.trades.append({
            "ticker": ticker,
            "buy_date": buy_date,
            "sell_date": sell_date,
            "earnings_date": earnings_date,
            "buy_price": round(buy_price, 2),
            "sell_price": round(sell_price, 2),
            "shares": shares,
            "cost": round(cost, 2),
            "proceeds": round(proceeds, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        })
        self.equity_curve.append(self.capital)

    def _get_prices(self, ticker: str, buy_date, sell_date) -> tuple[Optional[float], Optional[float]]:
        """Get buy and sell prices from local cache (batch-downloaded)"""
        df = self._price_cache.get(ticker)
        if df is None or df.empty:
            return None, None
        if not isinstance(buy_date, datetime):
            buy_date = datetime.combine(buy_date, datetime.min.time())
        if not isinstance(sell_date, datetime):
            sell_date = datetime.combine(sell_date, datetime.min.time())
        buf = max((sell_date - buy_date).days * 2, 10)
        start = buy_date - timedelta(days=buf)
        end = sell_date + timedelta(days=buf)
        sub = df.loc[start:end]
        if sub.empty:
            return None, None
        buy_mask = sub.index >= pd.Timestamp(buy_date)
        sell_mask = sub.index >= pd.Timestamp(sell_date)
        buy_rows = sub.loc[buy_mask]
        sell_rows = sub.loc[sell_mask]
        if buy_rows.empty or sell_rows.empty:
            return None, None
        return float(buy_rows["Close"].iloc[0]), float(sell_rows["Close"].iloc[0])

    def _summarize(self):
        """Print summary statistics"""
        df = pd.DataFrame(self.trades)
        if df.empty:
            print("No trades executed")
            return
        wins = df[df["pnl"] > 0]
        losses = df[df["pnl"] <= 0]
        print(f"\n{'='*50}")
        print(f"BACKTEST RESULTS")
        print(f"{'='*50}")
        print(f"Initial capital: ${self.initial_capital:.2f}")
        print(f"Final capital:   ${self.capital:.2f}")
        print(f"Total P&L:       ${self.capital - self.initial_capital:.2f}")
        print(f"Total return:    {((self.capital / self.initial_capital) - 1) * 100:.2f}%")
        print(f"Total trades:    {len(df)}")
        print(f"Winners:         {len(wins)} ({len(wins)/len(df)*100:.1f}%)")
        print(f"Losers:          {len(losses)} ({len(losses)/len(df)*100:.1f}%)")
        print(f"Avg win:         ${wins['pnl'].mean():.2f}" if not wins.empty else "")
        print(f"Avg loss:        ${losses['pnl'].mean():.2f}" if not losses.empty else "")
        dd = self._calc_max_drawdown()
        print(f"Max drawdown:    ${dd['max_dd_dollar']:.2f} ({dd['max_dd_pct']:.1f}%)")
        print(f"{'='*50}")
        path = f"{DATA_PROCESSED}/backtest_trades.csv"
        df.to_csv(path, index=False)
        print(f"Trades saved -> {path}")

    def get_summary(self) -> dict:
        df = pd.DataFrame(self.trades)
        dd = self._calc_max_drawdown()
        if df.empty:
            return {
                "initial_capital": self.initial_capital,
                "final_capital": self.capital,
                "total_return_pct": 0.0,
                "total_trades": 0,
                "win_rate": 0,
                "avg_win": 0,
                "avg_loss": 0,
                "max_drawdown_pct": 0,
            }
        return {
            "initial_capital": self.initial_capital,
            "final_capital": self.capital,
            "total_return_pct": round((self.capital / self.initial_capital - 1) * 100, 2),
            "total_trades": len(df),
            "win_rate": round(len(df[df["pnl"] > 0]) / len(df) * 100, 1) if len(df) > 0 else 0,
            "avg_win": round(df[df["pnl"] > 0]["pnl"].mean(), 2) if len(df[df["pnl"] > 0]) > 0 else 0,
            "avg_loss": round(df[df["pnl"] <= 0]["pnl"].mean(), 2) if len(df[df["pnl"] <= 0]) > 0 else 0,
            "max_drawdown_pct": dd["max_dd_pct"],
        }

    def _calc_max_drawdown(self) -> dict:
        """Calculate maximum drawdown from equity curve"""
        curve = np.array(self.equity_curve)
        peak = np.maximum.accumulate(curve)
        dd_pct = ((peak - curve) / peak * 100)
        max_dd_pct = float(dd_pct.max())
        max_dd_idx = int(dd_pct.argmax())
        max_dd_dollar = float(peak[max_dd_idx] - curve[max_dd_idx])
        return {"max_dd_pct": round(max_dd_pct, 2), "max_dd_dollar": round(max_dd_dollar, 2)}

def run(candidates: pd.DataFrame = None):
    if candidates is None:
        path = f"{DATA_PROCESSED}/filtered_candidates.csv"
        candidates = pd.read_csv(path) if pd.io.common.file_exists(path) else pd.DataFrame()
    if candidates.empty:
        print("No candidates to backtest")
        return
    bt = Backtest()
    bt.run_for_candidates(candidates)
    return bt

if __name__ == "__main__":
    run()
