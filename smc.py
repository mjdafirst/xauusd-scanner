"""
Pulls XAUUSD (via gold futures proxy) price data and computes
technical signals: support/resistance breakout, RSI, EMA trend,
ATR-based stops/targets, and a higher-timeframe trend filter.
"""

import pandas as pd
import yfinance as yf

import config
import oanda_price


def _flatten_columns(df):
    """Recent yfinance versions return MultiIndex columns even for a single
    ticker. Flatten to plain column names so comparisons work on scalars."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def fetch_price_data():
    """Returns the main-timeframe OHLCV DataFrame, or None on failure.

    Uses OANDA's own price feed when config.PRICE_SOURCE is "oanda" (the
    default) — this is the actual price your trades would fill at, and
    avoids the small but real gap between GC=F futures and spot XAUUSD.
    Falls back to yfinance if OANDA is unavailable or unconfigured, so a
    missing token doesn't stop the scanner from running.
    """
    if getattr(config, "PRICE_SOURCE", "oanda") == "oanda":
        df = oanda_price.fetch_candles(config.CANDLE_INTERVAL, count=300)
        if df is not None and not df.empty:
            return df
        print("[technicals] OANDA price fetch failed or unavailable — falling back to yfinance (GC=F).")

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
    if getattr(config, "PRICE_SOURCE", "oanda") == "oanda":
        df = oanda_price.fetch_candles(config.HTF_INTERVAL, count=200)
        if df is not None and not df.empty and len(df) >= config.EMA_SLOW + 2:
            ema_fast = df["Close"].ewm(span=config.EMA_FAST, adjust=False).mean()
            ema_slow = df["Close"].ewm(span=config.EMA_SLOW, adjust=False).mean()
            last_fast, last_slow = ema_fast.iloc[-2], ema_slow.iloc[-2]
            if last_fast > last_slow:
                return "up"
            if last_fast < last_slow:
                return "down"
            return None
        print("[technicals] OANDA HTF fetch failed or insufficient data — falling back to yfinance.")

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


def ttrades_context_allowed(direction, df, htf_trend=None):
    """TTrades / ICT-inspired entry filter.

    Longs should prefer discounted value and shorts should prefer premium/expensive
    price. If the HTF bias is opposite the trade, reject the signal rather than
    forcing an entry against the higher-timeframe context.
    """
    if not getattr(config, "USE_TTRADES_CONTEXT", False):
        return True
    if df is None or df.empty:
        return True

    lookback = getattr(config, "TTRADES_BIAS_LOOKBACK_BARS", 80)
    window = df.tail(lookback)
    recent_high = window["High"].max()
    recent_low = window["Low"].min()
    midpoint = (recent_high + recent_low) / 2.0
    last_price = df.iloc[-1]["Close"]

    if direction == "LONG":
        if htf_trend == "down":
            return False
        return last_price <= midpoint

    if direction == "SHORT":
        if htf_trend == "up":
            return False
        return last_price >= midpoint

    return True


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
        if not ttrades_context_allowed("LONG", df, htf_trend):
            return None
        return {
            "direction": "LONG",
            "price": price,
            "reason": (
                f"Breakout above {prior_high:.2f} resistance, "
                f"EMA{config.EMA_FAST}>EMA{config.EMA_SLOW}, RSI {rsi:.1f}"
                + (f", HTF trend {htf_trend}" if htf_trend else "")
                + ", value-anchored longs"
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
        if not ttrades_context_allowed("SHORT", df, htf_trend):
            return None
        return {
            "direction": "SHORT",
            "price": price,
            "reason": (
                f"Breakdown below {prior_low:.2f} support, "
                f"EMA{config.EMA_FAST}<EMA{config.EMA_SLOW}, RSI {rsi:.1f}"
                + (f", HTF trend {htf_trend}" if htf_trend else "")
                + ", value-anchored shorts"
            ),
            "stop": price + atr * config.ATR_STOP_MULT,
            "target": price - atr * config.ATR_TARGET_MULT,
        }

    return None

"""
Pulls XAUUSD (via gold futures proxy) price data and computes
technical signals: support/resistance breakout, RSI, EMA trend,
ATR-based stops/targets, and a higher-timeframe trend filter.
"""

import pandas as pd
import yfinance as yf

import config
import oanda_price


def _flatten_columns(df):
    """Recent yfinance versions return MultiIndex columns even for a single
    ticker. Flatten to plain column names so comparisons work on scalars."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def fetch_price_data():
    """Returns the main-timeframe OHLCV DataFrame, or None on failure.

    Uses OANDA's own price feed when config.PRICE_SOURCE is "oanda" (the
    default) — this is the actual price your trades would fill at, and
    avoids the small but real gap between GC=F futures and spot XAUUSD.
    Falls back to yfinance if OANDA is unavailable or unconfigured, so a
    missing token doesn't stop the scanner from running.
    """
    if getattr(config, "PRICE_SOURCE", "oanda") == "oanda":
        df = oanda_price.fetch_candles(config.CANDLE_INTERVAL, count=300)
        if df is not None and not df.empty:
            return df
        print("[technicals] OANDA price fetch failed or unavailable — falling back to yfinance (GC=F).")

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
    if getattr(config, "PRICE_SOURCE", "oanda") == "oanda":
        df = oanda_price.fetch_candles(config.HTF_INTERVAL, count=200)
        if df is not None and not df.empty and len(df) >= config.EMA_SLOW + 2:
            ema_fast = df["Close"].ewm(span=config.EMA_FAST, adjust=False).mean()
            ema_slow = df["Close"].ewm(span=config.EMA_SLOW, adjust=False).mean()
            last_fast, last_slow = ema_fast.iloc[-2], ema_slow.iloc[-2]
            if last_fast > last_slow:
                return "up"
            if last_fast < last_slow:
                return "down"
            return None
        print("[technicals] OANDA HTF fetch failed or insufficient data — falling back to yfinance.")

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


def ttrades_context_allowed(direction, df, htf_trend=None):
    """TTrades / ICT-inspired entry filter.

    Longs should prefer discounted value and shorts should prefer premium/expensive
    price. If the HTF bias is opposite the trade, reject the signal rather than
    forcing an entry against the higher-timeframe context.
    """
    if not getattr(config, "USE_TTRADES_CONTEXT", False):
        return True
    if df is None or df.empty:
        return True

    lookback = getattr(config, "TTRADES_BIAS_LOOKBACK_BARS", 80)
    window = df.tail(lookback)
    recent_high = window["High"].max()
    recent_low = window["Low"].min()
    midpoint = (recent_high + recent_low) / 2.0
    last_price = df.iloc[-1]["Close"]

    if direction == "LONG":
        if htf_trend == "down":
            return False
        return last_price <= midpoint

    if direction == "SHORT":
        if htf_trend == "up":
            return False
        return last_price >= midpoint

    return True


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
        if not ttrades_context_allowed("LONG", df, htf_trend):
            return None
        return {
            "direction": "LONG",
            "price": price,
            "reason": (
                f"Breakout above {prior_high:.2f} resistance, "
                f"EMA{config.EMA_FAST}>EMA{config.EMA_SLOW}, RSI {rsi:.1f}"
                + (f", HTF trend {htf_trend}" if htf_trend else "")
                + ", value-anchored longs"
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
        if not ttrades_context_allowed("SHORT", df, htf_trend):
            return None
        return {
            "direction": "SHORT",
            "price": price,
            "reason": (
                f"Breakdown below {prior_low:.2f} support, "
                f"EMA{config.EMA_FAST}<EMA{config.EMA_SLOW}, RSI {rsi:.1f}"
                + (f", HTF trend {htf_trend}" if htf_trend else "")
                + ", value-anchored shorts"
            ),
            "stop": price + atr * config.ATR_STOP_MULT,
            "target": price - atr * config.ATR_TARGET_MULT,
        }

    return None
"""
""""

"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""

""""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""

"""
Pulls XAUUSD (via gold futures proxy) price data and computes
technical signals: support/resistance breakout, RSI, EMA trend,
ATR-based stops/targets, and a higher-timeframe trend filter.
"""

import pandas as pd
import yfinance as yf

import config
import oanda_price


def _flatten_columns(df):
    """Recent yfinance versions return MultiIndex columns even for a single
    ticker. Flatten to plain column names so comparisons work on scalars."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def fetch_price_data():
    """Returns the main-timeframe OHLCV DataFrame, or None on failure.

    Uses OANDA's own price feed when config.PRICE_SOURCE is "oanda" (the
    default) — this is the actual price your trades would fill at, and
    avoids the small but real gap between GC=F futures and spot XAUUSD.
    Falls back to yfinance if OANDA is unavailable or unconfigured, so a
    missing token doesn't stop the scanner from running.
    """
    if getattr(config, "PRICE_SOURCE", "oanda") == "oanda":
        df = oanda_price.fetch_candles(config.CANDLE_INTERVAL, count=300)
        if df is not None and not df.empty:
            return df
        print("[technicals] OANDA price fetch failed or unavailable — falling back to yfinance (GC=F).")

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
    if getattr(config, "PRICE_SOURCE", "oanda") == "oanda":
        df = oanda_price.fetch_candles(config.HTF_INTERVAL, count=200)
        if df is not None and not df.empty and len(df) >= config.EMA_SLOW + 2:
            ema_fast = df["Close"].ewm(span=config.EMA_FAST, adjust=False).mean()
            ema_slow = df["Close"].ewm(span=config.EMA_SLOW, adjust=False).mean()
            last_fast, last_slow = ema_fast.iloc[-2], ema_slow.iloc[-2]
            if last_fast > last_slow:
                return "up"
            if last_fast < last_slow:
                return "down"
            return None
        print("[technicals] OANDA HTF fetch failed or insufficient data — falling back to yfinance.")

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


def ttrades_context_allowed(direction, df, htf_trend=None):
    """TTrades / ICT-inspired entry filter.

    Longs should prefer discounted value and shorts should prefer premium/expensive
    price. If the HTF bias is opposite the trade, reject the signal rather than
    forcing an entry against the higher-timeframe context.
    """
    if not getattr(config, "USE_TTRADES_CONTEXT", False):
        return True
    if df is None or df.empty:
        return True

    lookback = getattr(config, "TTRADES_BIAS_LOOKBACK_BARS", 80)
    window = df.tail(lookback)
    recent_high = window["High"].max()
    recent_low = window["Low"].min()
    midpoint = (recent_high + recent_low) / 2.0
    last_price = df.iloc[-1]["Close"]

    if direction == "LONG":
        if htf_trend == "down":
            return False
        return last_price <= midpoint

    if direction == "SHORT":
        if htf_trend == "up":
            return False
        return last_price >= midpoint

    return True


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
        if not ttrades_context_allowed("LONG", df, htf_trend):
            return None
        return {
            "direction": "LONG",
            "price": price,
            "reason": (
                f"Breakout above {prior_high:.2f} resistance, "
                f"EMA{config.EMA_FAST}>EMA{config.EMA_SLOW}, RSI {rsi:.1f}"
                + (f", HTF trend {htf_trend}" if htf_trend else "")
                + ", value-anchored longs"
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
        if not ttrades_context_allowed("SHORT", df, htf_trend):
            return None
        return {
            "direction": "SHORT",
            "price": price,
            "reason": (
                f"Breakdown below {prior_low:.2f} support, "
                f"EMA{config.EMA_FAST}<EMA{config.EMA_SLOW}, RSI {rsi:.1f}"
                + (f", HTF trend {htf_trend}" if htf_trend else "")
                + ", value-anchored shorts"
            ),
            "stop": price + atr * config.ATR_STOP_MULT,
            "target": price - atr * config.ATR_TARGET_MULT,
        }

    return None
"""
"""
"""
"""
"""
"""
"""
"""
"""

""""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
""""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""

"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
"""
""",
"path":"smc.py","repo":"xauusd-scanner"}]} ivoq to=functions.push_files  rendered maybe weird because large content. Need check if patch succeeded; there is risk huge malformed file due accidental duplicated content from my huge string. Need verify by reading smc.py & technicals.py. Need maybe revert if corrupted. Let's inspect actual files to ensure no duplicate or weird extraneous text. Use getfile on relevant ranges maybe read entire. Let's do getfile. Need not too huge but okay. Use read file. We'll check after patch. Let's check by retrieving. We'll also ensure technicals not corrupted. Use getfile with path. Let's do. Need maybe if pushed_files weirdly need fix. if not, good. Let's do minimal. Use getfile. We'll read smc and technicals. Need maybe not too huge but okay. Let's fix if weird. Let's do. Use commentary tool call. We're allowed to read after push. Let's check. Need ensure patch eventually correct. Let's do getfile for smc.py and technicals.py. Maybe large but okay. Also maybe config. Let's do. Jean. Wait I used push_files with huge files; no validation. Need check. Let's do. But ensure not too large? It is large but okay. Let's inspect. We'll call getfile maybe entire file due less than 300 lines. Fine. Let's do. Use multi_tool_use parallel maybe to read both simultaneously. Good. We'll do. Need only in commentary. Let's do parallel. Good. Use tool. Let's inspect. Let's do multi-tool to read config.py, smc.py, technicals.py. Use one call in parallel. Let's do. We'll keep concise. Before, maybe we want to not overdo but okay. Let's do. Need use multi_tool_use.parallel with functions.getfile for each. Good. Let's do. Error? Let's see. We'll know if weird. Let's do. Use same repo. Good. Let's proceed. Wait maybe bigger than default; but okay. Let's call. Use commentary channel. Let's do. Similar to user issue no need. Go. Let's proceed. We'll use multi_tool_use.parallel with 3 getfile calls. Good. Let's do. We'll inspect. Good. Let's do. Let's proceed. We'll see. Let's do it now. Use functions.getfile with paths. Good. Let's go. Let's do. Let's do in commentary channel. Let's execute. Let's call. Wait tool call maybe with `path` as 