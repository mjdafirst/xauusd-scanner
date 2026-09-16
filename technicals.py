"""
Pulls XAUUSD (via gold futures proxy) price data and computes
technical signals: support/resistance breakout, RSI, EMA trend,
ATR-based stops/targets, and a higher-timeframe trend filter.
"""

import pandas as pd
import yfinance as yf

import config


def _flatten_columns(df):
    """Recent yfinance versions return MultiIndex columns even for a single
    ticker. Flatten to plain column names so comparisons work on scalars."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def fetch_price_data():
    """Returns the main-timeframe OHLCV DataFrame, or None on failure."""
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
        df = _flatten_columns(df)
        df = df.dropna()
        return df
    except Exception as e:
        print(f"[technicals] Failed to fetch price data: {e}")
        return None


def fetch_htf_trend():
    """
    Fetches higher-timeframe data and returns "up", "down", or None
    (None means unknown/unavailable — callers should treat that as
    "don't filter" rather than blocking every signal).
    """
    try:
        df = yf.download(
            tickers=config.TICKER,
            period=config.HTF_LOOKBACK_PERIOD,
            interval=config.HTF_INTERVAL,
            progress=False,
        )
        if df.empty:
            print("[technicals] No HTF data returned.")
            return None
        df = _flatten_columns(df).dropna()
        if len(df) < config.EMA_SLOW + 2:
            return None

        ema_fast = df["Close"].ewm(span=config.EMA_FAST, adjust=False).mean()
        ema_slow = df["Close"].ewm(span=config.EMA_SLOW, adjust=False).mean()
        last_fast = ema_fast.iloc[-2]   # last fully closed HTF candle
        last_slow = ema_slow.iloc[-2]

        if last_fast > last_slow:
            return "up"
        if last_fast < last_slow:
            return "down"
        return None
    except Exception as e:
        print(f"[technicals] Failed to fetch HTF trend: {e}")
        return None


def compute_rsi(series, period):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def compute_atr(df, period):
    """Average True Range — measures typical bar-to-bar volatility, used to
    size stops/targets so they adapt to how choppy or calm the market is."""
    prev_close = df["Close"].shift(1)
    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - prev_close).abs()
    tr3 = (df["Low"] - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.rolling(period).mean()


def compute_indicators(df):
    df = df.copy()
    df["RSI"] = compute_rsi(df["Close"], config.RSI_PERIOD)
    df["EMA_FAST"] = df["Close"].ewm(span=config.EMA_FAST, adjust=False).mean()
    df["EMA_SLOW"] = df["Close"].ewm(span=config.EMA_SLOW, adjust=False).mean()
    df["Recent_High"] = df["High"].rolling(config.SR_LOOKBACK_BARS).max()
    df["Recent_Low"] = df["Low"].rolling(config.SR_LOOKBACK_BARS).min()
    df["ATR"] = compute_atr(df, config.ATR_PERIOD)
    return df


def detect_signal(df, htf_trend=None):
    """
    Looks at the most recently CLOSED candle and returns a signal dict
    or None.

    htf_trend: "up", "down", or None (unknown). When known, a breakout
    is only taken if the higher-timeframe trend agrees with it — this
    filters out breakouts that fire against the bigger picture and tend
    to fail quickly. When unknown, the filter is skipped rather than
    blocking every signal.
    """
    min_bars = max(config.SR_LOOKBACK_BARS, config.EMA_SLOW, config.ATR_PERIOD) + 2
    if df is None or len(df) < min_bars:
        return None

    df = compute_indicators(df)
    last = df.iloc[-2]      # last fully closed candle
    prior_high = df["Recent_High"].iloc[-3]  # S/R computed before this candle
    prior_low = df["Recent_Low"].iloc[-3]

    price = last["Close"]
    rsi = last["RSI"]
    atr = last["ATR"]
    trend_up = last["EMA_FAST"] > last["EMA_SLOW"]
    trend_down = last["EMA_FAST"] < last["EMA_SLOW"]

    if pd.isna(atr) or atr <= 0:
        return None  # not enough data yet for a reliable ATR

    # Bullish breakout: price closes above recent resistance, trend agrees,
    # RSI not already overbought, and (if known) HTF trend isn't against it
    if (
        price > prior_high
        and trend_up
        and rsi < config.RSI_OVERBOUGHT
        and htf_trend != "down"
    ):
        return {
            "direction": "LONG",
            "price": price,
            "reason": (
                f"Breakout above {prior_high:.2f} resistance, "
                f"EMA{config.EMA_FAST}>EMA{config.EMA_SLOW}, RSI {rsi:.1f}"
                + (f", HTF trend {htf_trend}" if htf_trend else "")
            ),
            "stop": price - atr * config.ATR_STOP_MULT,
            "target": price + atr * config.ATR_TARGET_MULT,
        }

    # Bearish breakdown: price closes below recent support, trend agrees,
    # RSI not already oversold, and (if known) HTF trend isn't against it
    if (
        price < prior_low
        and trend_down
        and rsi > config.RSI_OVERSOLD
        and htf_trend != "up"
    ):
        return {
            "direction": "SHORT",
            "price": price,
            "reason": (
                f"Breakdown below {prior_low:.2f} support, "
                f"EMA{config.EMA_FAST}<EMA{config.EMA_SLOW}, RSI {rsi:.1f}"
                + (f", HTF trend {htf_trend}" if htf_trend else "")
            ),
            "stop": price + atr * config.ATR_STOP_MULT,
            "target": price - atr * config.ATR_TARGET_MULT,
        }

    return None
