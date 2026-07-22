import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from src.config import DATA_PROCESSED, OUTPUT_DIR

sns.set_theme(style="darkgrid")

def plot_k_distribution(df: pd.DataFrame, title: str = "K Distribution"):
    plt.figure(figsize=(10, 6))
    plt.hist(df["avg_K"].dropna(), bins=50, edgecolor="black", alpha=0.7)
    plt.axvline(x=0.9, color="r", linestyle="--", label="K=0.9 (low)")
    plt.axvline(x=1.0, color="g", linestyle="--", label="K=1.0 (par)")
    plt.axvline(x=1.1, color="b", linestyle="--", label="K=1.1 (threshold)")
    plt.xlabel("Average K")
    plt.ylabel("Count")
    plt.title(title)
    plt.legend()
    path = f"{OUTPUT_DIR}/k_distribution.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved -> {path}")
    plt.close()

def plot_k_time_series(ticker: str):
    path = f"{DATA_PROCESSED}/{ticker}_K.csv"
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        return
    plt.figure(figsize=(12, 6))
    plt.plot(df["year"], df["K"], "o-", label="K", linewidth=2)
    plt.plot(df["year"], df["KI"], "s--", label="KI (positioning)")
    plt.plot(df["year"], df["KR"], "d--", label="KR (efficiency)")
    plt.plot(df["year"], df["KF"], "v--", label="KF (liquidity)")
    plt.axhline(y=1.0, color="gray", linestyle=":")
    plt.xlabel("Year")
    plt.ylabel("Value")
    plt.title(f"{ticker} - K Components Over Time")
    plt.legend()
    path = f"{OUTPUT_DIR}/{ticker}_K_components.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved -> {path}")
    plt.close()

def plot_equity_curve(equity_curve: list[float]):
    plt.figure(figsize=(12, 6))
    plt.plot(equity_curve, linewidth=2)
    plt.xlabel("Trade #")
    plt.ylabel("Capital ($)")
    plt.title("Backtest Equity Curve")
    plt.grid(True, alpha=0.3)
    path = f"{OUTPUT_DIR}/equity_curve.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved -> {path}")
    plt.close()

def plot_trades_summary(df_trades: pd.DataFrame):
    if df_trades.empty:
        return
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    ax = axes[0, 0]
    colors = ["g" if x > 0 else "r" for x in df_trades["pnl_pct"]]
    ax.bar(range(len(df_trades)), df_trades["pnl_pct"], color=colors, alpha=0.7)
    ax.set_xlabel("Trade #")
    ax.set_ylabel("P&L %")
    ax.set_title("Trade Returns")
    ax = axes[0, 1]
    df_trades[df_trades["pnl"] > 0]["pnl_pct"].hist(
        ax=ax, bins=20, alpha=0.7, color="g"
    )
    df_trades[df_trades["pnl"] <= 0]["pnl_pct"].hist(
        ax=ax, bins=20, alpha=0.7, color="r"
    )
    ax.set_xlabel("P&L %")
    ax.set_ylabel("Count")
    ax.set_title("Win/Loss Distribution")
    ax = axes[1, 0]
    win_rate = (df_trades["pnl"] > 0).mean() * 100
    ax.pie(
        [win_rate, 100 - win_rate],
        labels=[f"Wins {win_rate:.0f}%", f"Losses {100-win_rate:.0f}%"],
        colors=["g", "r"],
        autopct="%1.1f%%",
    )
    ax.set_title("Win Rate")
    ax = axes[1, 1]
    cumulative = df_trades["pnl"].cumsum()
    ax.fill_between(range(len(cumulative)), cumulative, alpha=0.3)
    ax.plot(cumulative, linewidth=2)
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Cumulative P&L ($)")
    ax.set_title("Cumulative P&L")
    plt.tight_layout()
    path = f"{OUTPUT_DIR}/trades_summary.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved -> {path}")
    plt.close()

def run():
    df_k = pd.read_csv(f"{DATA_PROCESSED}/all_K_ratings.csv") if pd.io.common.file_exists(f"{DATA_PROCESSED}/all_K_ratings.csv") else pd.DataFrame()
    if not df_k.empty:
        plot_k_distribution(df_k)
        top = df_k.head(10)["ticker"].tolist()
        for t in top:
            plot_k_time_series(t)
    trades_path = f"{DATA_PROCESSED}/backtest_trades.csv"
    df_trades = pd.read_csv(trades_path) if pd.io.common.file_exists(trades_path) else pd.DataFrame()
    if not df_trades.empty:
        plot_trades_summary(df_trades)
    print(f"All charts saved to {OUTPUT_DIR}/")

if __name__ == "__main__":
    run()
