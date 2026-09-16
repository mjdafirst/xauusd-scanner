"""
Backtests the scanner's breakout strategy against historical XAUUSD
(gold futures proxy) data, so you can see how it would have performed
before trusting live alerts.

This is intentionally simple: for each historical bar, it checks the same
breakout/trend/RSI/ATR conditions the live scanner uses, and if a signal
fires, walks forward to see whether the ATR-based stop or target was hit
first. It does NOT account for slippage, spread, commissions, or the news
blackout filter — treat results as a rough sanity check of the entry
logic, not a precise P&L simulation.

Usage:
    python backtest.py
    python backtest.py --interval 15m --period 60d
    python backtest.py --max-hold-bars 96

Note: yfinance limits how much intraday history is available — e.g. ~60
days for 15m bars. For a longer look-back, use a coarser interval (like 1h).
"""

import argparse

import pandas as pd
import yfinance as yf

import config
import technicals


def fetch_backtest_data(interval, period):
    df = yf.download(tickers=config.TICKER, period=period, interval=interval, progress=False)
    if df.empty:
        raise SystemExit(f"No data returned for interval={interval}, period={period}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()


def simulate(df, max_hold_bars):
    """
    Walks through the historical data bar by bar, re-using the exact same
    detect_signal() logic the live scanner uses (no higher-timeframe filter
    here, to keep the backtest self-contained on one dataset — results will
    be somewhat more permissive than live trading, which does apply it).
    """
    df = technicals.compute_indicators(df)
    trades = []

    min_bars = max(config.SR_LOOKBACK_BARS, config.EMA_SLOW, config.ATR_PERIOD) + 2

    for i in range(min_bars, len(df) - 1):
        window = df.iloc[: i + 1]  # only data "known" up to this point, no lookahead
        signal = technicals.detect_signal(window)
        if not signal:
            continue

        entry_price = signal["price"]
        stop = signal["stop"]
        target = signal["target"]
        direction = signal["direction"]
        entry_time = df.index[i - 1]  # detect_signal looks at iloc[-2] of the window

        outcome = "no_hit"
        exit_price = None
        for j in range(i, min(i + max_hold_bars, len(df))):
            bar = df.iloc[j]
            if direction == "LONG":
                if bar["Low"] <= stop:
                    outcome, exit_price = "stop", stop
                    break
                if bar["High"] >= target:
                    outcome, exit_price = "target", target
                    break
            else:  # SHORT
                if bar["High"] >= stop:
                    outcome, exit_price = "stop", stop
                    break
                if bar["Low"] <= target:
                    outcome, exit_price = "target", target
                    break

        trades.append({
            "entry_time": entry_time,
            "direction": direction,
            "entry": entry_price,
            "stop": stop,
            "target": target,
            "outcome": outcome,
        })

    return trades


def summarize(trades):
    if not trades:
        print("No signals fired in this period — try a longer period, a different "
              "interval, or looser thresholds in config.py.")
        return

    total = len(trades)
    wins = sum(1 for t in trades if t["outcome"] == "target")
    losses = sum(1 for t in trades if t["outcome"] == "stop")
    no_hit = sum(1 for t in trades if t["outcome"] == "no_hit")

    decided = wins + losses
    win_rate = (wins / decided * 100) if decided else 0.0

    r_multiple = config.ATR_TARGET_MULT / config.ATR_STOP_MULT
    expectancy_r = (win_rate / 100 * r_multiple) - ((100 - win_rate) / 100 * 1)

    print(f"\n--- Backtest summary ({config.TICKER}) ---")
    print(f"Total signals:     {total}")
    print(f"Hit target:        {wins}")
    print(f"Hit stop:          {losses}")
    print(f"No hit in window:  {no_hit}")
    print(f"Win rate (decided): {win_rate:.1f}%")
    print(f"Reward:risk ratio:  1:{r_multiple:.2f}")
    print(f"Expectancy:        {expectancy_r:+.2f}R per trade (rough, excludes fees/slippage/no_hit trades)")
    print("\nBreakdown by direction:")
    for direction in ("LONG", "SHORT"):
        d_trades = [t for t in trades if t["direction"] == direction]
        d_wins = sum(1 for t in d_trades if t["outcome"] == "target")
        d_losses = sum(1 for t in d_trades if t["outcome"] == "stop")
        d_decided = d_wins + d_losses
        d_rate = (d_wins / d_decided * 100) if d_decided else 0.0
        print(f"  {direction}: {len(d_trades)} signals, {d_rate:.1f}% win rate ({d_wins}W / {d_losses}L)")


def main():
    parser = argparse.ArgumentParser(description="Backtest the XAUUSD scanner strategy.")
    parser.add_argument("--interval", default=config.CANDLE_INTERVAL,
                         help="Candle interval (default: same as config.py, e.g. 15m)")
    parser.add_argument("--period", default="60d",
                         help="History length, e.g. 30d, 60d, 2y (yfinance limits intraday history)")
    parser.add_argument("--max-hold-bars", type=int, default=96,
                         help="Max bars to hold a trade before giving up (default 96 = 24h at 15m bars)")
    parser.add_argument("--csv", default=None, help="Optional path to save all trades as CSV")
    args = parser.parse_args()

    print(f"Fetching {args.period} of {args.interval} data for {config.TICKER}...")
    df = fetch_backtest_data(args.interval, args.period)
    print(f"Got {len(df)} bars. Running simulation...")

    trades = simulate(df, args.max_hold_bars)
    summarize(trades)

    if args.csv and trades:
        pd.DataFrame(trades).to_csv(args.csv, index=False)
        print(f"\nSaved {len(trades)} trades to {args.csv}")


if __name__ == "__main__":
    main()
