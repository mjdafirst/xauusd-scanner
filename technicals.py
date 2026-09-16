"""
Pulls XAUUSD (via gold futures proxy) price data and computes
technical signals: support/resistance breakout, RSI, EMA trend.
"""

import pandas as pd
import yfinance as yf

import config


def fetch_price_data():
    """Returns a DataFrame with OHLCV data, or None on failure."""
    try:
        df = yf.download(
            tickers=config.TICKER,
            period=config.LOOKBACK_PERIOD,
            interval=config.CANDLE_INTERVAL,
            progress=False,
        )
        if df.empty:
            print("[technicals] No data returned.")
            return None
        df = df.dropna()
        return df
    except Exception as e:
        print(f"[technicals] Failed to fetch price data: {e}")
        return None


def compute_rsi(series, period):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def compute_indicators(df):
    df = df.copy()
    df["RSI"] = compute_rsi(df["Close"], config.RSI_PERIOD)
    df["EMA_FAST"] = df["Close"].ewm(span=config.EMA_FAST, adjust=False).mean()
    df["EMA_SLOW"] = df["Close"].ewm(span=config.EMA_SLOW, adjust=False).mean()
    df["Recent_High"] = df["High"].rolling(config.SR_LOOKBACK_BARS).max()
    df["Recent_Low"] = df["Low"].rolling(config.SR_LOOKBACK_BARS).min()
    return df


def detect_signal(df):
    """
    Looks at the most recently CLOSED candle and returns a signal dict
    or None. Keeps the logic simple and explainable on purpose —
    tune thresholds in config.py as you learn what works.
    """
    if df is None or len(df) < max(config.SR_LOOKBACK_BARS, config.EMA_SLOW) + 2:
        return None

    df = compute_indicators(df)
    last = df.iloc[-2]      # last fully closed candle
    prior_high = df["Recent_High"].iloc[-3]  # S/R computed before this candle
    prior_low = df["Recent_Low"].iloc[-3]

    price = last["Close"]
    rsi = last["RSI"]
    trend_up = last["EMA_FAST"] > last["EMA_SLOW"]
    trend_down = last["EMA_FAST"] < last["EMA_SLOW"]

    # Bullish breakout: price closes above recent resistance, trend agrees, RSI not already overbought
    if price > prior_high and trend_up and rsi < config.RSI_OVERBOUGHT:
        return {
            "direction": "LONG",
            "price": price,
            "reason": f"Breakout above {prior_high:.2f} resistance, EMA{config.EMA_FAST}>EMA{config.EMA_SLOW}, RSI {rsi:.1f}",
            "stop": prior_low,
            "target": price + (price - prior_low),  # simple 1:1 R multiple to start
        }

    # Bearish breakdown: price closes below recent support, trend agrees, RSI not already oversold
    if price < prior_low and trend_down and rsi > config.RSI_OVERSOLD:
        return {
            "direction": "SHORT",
            "price": price,
            "reason": f"Breakdown below {prior_low:.2f} support, EMA{config.EMA_FAST}<EMA{config.EMA_SLOW}, RSI {rsi:.1f}",
            "stop": prior_high,
            "target": price - (prior_high - price),
        }

    return None
