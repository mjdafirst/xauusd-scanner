"""Price data, indicators, and breakout signals for XAUUSD."""

import pandas as pd
import yfinance as yf

import config
import oanda_price


def _flatten_columns(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def fetch_price_data():
    if getattr(config, "PRICE_SOURCE", "oanda") == "oanda":
        df = oanda_price.fetch_candles(config.CANDLE_INTERVAL, count=300)
        if df is not None and not df.empty:
            return df
        print("[technicals] OANDA fetch failed; falling back to yfinance.")
    try:
        df = yf.download(tickers=config.TICKER, period=config.LOOKBACK_PERIOD,
                         interval=config.CANDLE_INTERVAL, progress=False)
        if df.empty:
            return None
        return _flatten_columns(df).dropna()
    except Exception as exc:
        print(f"[technicals] Failed to fetch price data: {exc}")
        return None


def fetch_htf_trend():
    if getattr(config, "PRICE_SOURCE", "oanda") == "oanda":
        df = oanda_price.fetch_candles(config.HTF_INTERVAL, count=200)
        if df is not None and not df.empty and len(df) >= config.EMA_SLOW + 2:
            fast = df["Close"].ewm(span=config.EMA_FAST, adjust=False).mean()
            slow = df["Close"].ewm(span=config.EMA_SLOW, adjust=False).mean()
            if fast.iloc[-2] > slow.iloc[-2]:
                return "up"
            if fast.iloc[-2] < slow.iloc[-2]:
                return "down"
            return None
    try:
        df = yf.download(tickers=config.TICKER, period=config.HTF_LOOKBACK_PERIOD,
                         interval=config.HTF_INTERVAL, progress=False)
        if df.empty:
            return None
        df = _flatten_columns(df).dropna()
        if len(df) < config.EMA_SLOW + 2:
            return None
        fast = df["Close"].ewm(span=config.EMA_FAST, adjust=False).mean()
        slow = df["Close"].ewm(span=config.EMA_SLOW, adjust=False).mean()
        if fast.iloc[-2] > slow.iloc[-2]:
            return "up"
        if fast.iloc[-2] < slow.iloc[-2]:
            return "down"
        return None
    except Exception as exc:
        print(f"[technicals] Failed to fetch HTF data: {exc}")
        return None


def compute_rsi(series, period):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(period).mean() / loss.rolling(period).mean().replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def compute_atr(df, period):
    previous = df["Close"].shift(1)
    ranges = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - previous).abs(),
        (df["Low"] - previous).abs(),
    ], axis=1)
    return ranges.max(axis=1).rolling(period).mean()


def compute_indicators(df):
    result = df.copy()
    result["RSI"] = compute_rsi(result["Close"], config.RSI_PERIOD)
    result["EMA_FAST"] = result["Close"].ewm(span=config.EMA_FAST, adjust=False).mean()
    result["EMA_SLOW"] = result["Close"].ewm(span=config.EMA_SLOW, adjust=False).mean()
    result["Recent_High"] = result["High"].rolling(config.SR_LOOKBACK_BARS).max()
    result["Recent_Low"] = result["Low"].rolling(config.SR_LOOKBACK_BARS).min()
    result["ATR"] = compute_atr(result, config.ATR_PERIOD)
    return result


def ttrades_context_allowed(direction, df, htf_trend=None):
    """Prefer longs in discount and shorts in premium of the recent range."""
    if not getattr(config, "USE_TTRADES_CONTEXT", False) or df is None or df.empty:
        return True
    window = df.tail(getattr(config, "TTRADES_BIAS_LOOKBACK_BARS", 80))
    midpoint = (window["High"].max() + window["Low"].min()) / 2
    price = df.iloc[-1]["Close"]
    if direction == "LONG":
        return htf_trend != "down" and price <= midpoint
    if direction == "SHORT":
        return htf_trend != "up" and price >= midpoint
    return True


def detect_signal(df, htf_trend=None):
    min_bars = max(config.SR_LOOKBACK_BARS, config.EMA_SLOW, config.ATR_PERIOD) + 2
    if df is None or len(df) < min_bars:
        return None
    df = compute_indicators(df)
    last = df.iloc[-2]
    prior_high = df["Recent_High"].iloc[-3]
    prior_low = df["Recent_Low"].iloc[-3]
    price, rsi, atr = last["Close"], last["RSI"], last["ATR"]
    if pd.isna(atr) or atr <= 0:
        return None
    trend_up = last["EMA_FAST"] > last["EMA_SLOW"]
    trend_down = last["EMA_FAST"] < last["EMA_SLOW"]
    if price > prior_high and trend_up and rsi < config.RSI_OVERBOUGHT and htf_trend != "down":
        if not ttrades_context_allowed("LONG", df.iloc[:-1], htf_trend):
            return None
        return {"direction": "LONG", "price": price,
                "reason": f"Breakout above {prior_high:.2f}, EMA trend up, RSI {rsi:.1f}, value context",
                "stop": price - atr * config.ATR_STOP_MULT,
                "target": price + atr * config.ATR_TARGET_MULT}
    if price < prior_low and trend_down and rsi > config.RSI_OVERSOLD and htf_trend != "up":
        if not ttrades_context_allowed("SHORT", df.iloc[:-1], htf_trend):
            return None
        return {"direction": "SHORT", "price": price,
                "reason": f"Breakdown below {prior_low:.2f}, EMA trend down, RSI {rsi:.1f}, value context",
                "stop": price + atr * config.ATR_STOP_MULT,
                "target": price - atr * config.ATR_TARGET_MULT}
    return None
