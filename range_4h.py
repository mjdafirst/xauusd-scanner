"""4H Range Scalping with False-Breakout Filters.

Strategy inspired by @BedaKakuru48767:
1. First 4H candle of the New York day (00:00 - 04:00 NY time).
2. 5M breakout outside the 4H range (must close outside).
3. 5M re-entry close back inside the range with displacement.
4. Two-candle follow-through confirmation and HTF trend alignment.
5. 1:2 Risk-to-Reward target with stop beyond breakout swing extreme.
"""

import pandas as pd
import config
import technicals


def get_first_4h_range_ny(df):
    """Calculates the Range High and Range Low of the first 4H candle in NY time."""
    if df is None or len(df) < 50:
        return None, None
        
    df_copy = df.copy()
    if not isinstance(df_copy.index, pd.DatetimeIndex):
        df_copy.index = pd.to_datetime(df_copy.index, utc=True)
        
    ny_index = df_copy.index.tz_convert("America/New_York")
    df_copy["time_ny"] = ny_index
    df_copy["date_ny"] = ny_index.date
    
    current_date = df_copy["date_ny"].iloc[-1]
    day_bars = df_copy[df_copy["date_ny"] == current_date]
    
    c4h_bars = day_bars[(day_bars["time_ny"].dt.hour >= 0) & (day_bars["time_ny"].dt.hour < 4)]
    if len(c4h_bars) < 6:
        return None, None
        
    range_high = float(c4h_bars["High"].max())
    range_low = float(c4h_bars["Low"].min())
    return range_high, range_low


def detect_range_4h_signal(df, htf_trend=None):
    """Detects 4H Range Fakeout & Re-entry signals with displacement filters."""
    min_bars = 60
    if df is None or len(df) < min_bars:
        return None
        
    closed = df.iloc[:-1].copy()
    indicators = technicals.compute_indicators(closed)
    atr = indicators["ATR"].iloc[-1]
    if pd.isna(atr) or atr <= 0:
        return None
        
    range_high, range_low = get_first_4h_range_ny(closed)
    if range_high is None or range_low is None:
        return None
        
    last_time = closed.index[-1]
    last_time_ny = last_time.tz_convert("America/New_York") if last_time.tzinfo else last_time
    if last_time_ny.hour < 4:
        return None
        
    lookback = closed.tail(30)
    
    # Bearish Setup (Breakout above Range High -> Displacement Re-entry below Range High)
    highs_outside = lookback[lookback["Close"] > range_high]
    if not highs_outside.empty and htf_trend != "up":
        breakout_idx = highs_outside.index[-1]
        breakout_bar_pos = lookback.index.get_loc(breakout_idx)
        since_breakout = lookback.iloc[breakout_bar_pos:]
        
        reentries = since_breakout[since_breakout["Close"] < range_high]
        if not reentries.empty:
            reentry_idx = reentries.index[-1]
            reentry_bar = closed.loc[reentry_idx]
            
            body = abs(reentry_bar["Close"] - reentry_bar["Open"])
            total_range = reentry_bar["High"] - reentry_bar["Low"]
            if total_range > 0 and (body / total_range) >= 0.40:
                swing_high = float(since_breakout["High"].max())
                max_allowed_extension = getattr(config, "RANGE_4H_MAX_EXT_ATR", 4.0) * atr
                if (swing_high - range_high) <= max_allowed_extension:
                    entry = float(closed["Close"].iloc[-1])
                    stop = swing_high + 0.25 * atr
                    risk = stop - entry
                    if risk > 0.5:
                        target = entry - getattr(config, "MIN_RISK_REWARD", 2.0) * risk
                        if closed["Close"].iloc[-1] <= reentry_bar["Low"] or closed.index[-1] == reentry_idx:
                            return {
                                "direction": "SHORT",
                                "price": entry,
                                "stop": stop,
                                "target": target,
                                "reason": (
                                    f"4H Range Fakeout above {range_high:.2f} (Extreme: {swing_high:.2f}), "
                                    f"Displacement Re-entry into range [4H: {range_low:.2f}-{range_high:.2f}]"
                                    + (f", HTF {htf_trend}" if htf_trend else "")
                                )
                            }
                            
    # Bullish Setup (Breakout below Range Low -> Displacement Re-entry above Range Low)
    lows_outside = lookback[lookback["Close"] < range_low]
    if not lows_outside.empty and htf_trend != "down":
        breakout_idx = lows_outside.index[-1]
        breakout_bar_pos = lookback.index.get_loc(breakout_idx)
        since_breakout = lookback.iloc[breakout_bar_pos:]
        
        reentries = since_breakout[since_breakout["Close"] > range_low]
        if not reentries.empty:
            reentry_idx = reentries.index[-1]
            reentry_bar = closed.loc[reentry_idx]
            
            body = abs(reentry_bar["Close"] - reentry_bar["Open"])
            total_range = reentry_bar["High"] - reentry_bar["Low"]
            if total_range > 0 and (body / total_range) >= 0.40:
                swing_low = float(since_breakout["Low"].min())
                max_allowed_extension = getattr(config, "RANGE_4H_MAX_EXT_ATR", 4.0) * atr
                if (range_low - swing_low) <= max_allowed_extension:
                    entry = float(closed["Close"].iloc[-1])
                    stop = swing_low - 0.25 * atr
                    risk = entry - stop
                    if risk > 0.5:
                        target = entry + getattr(config, "MIN_RISK_REWARD", 2.0) * risk
                        if closed["Close"].iloc[-1] >= reentry_bar["High"] or closed.index[-1] == reentry_idx:
                            return {
                                "direction": "LONG",
                                "price": entry,
                                "stop": stop,
                                "target": target,
                                "reason": (
                                    f"4H Range Fakeout below {range_low:.2f} (Extreme: {swing_low:.2f}), "
                                    f"Displacement Re-entry into range [4H: {range_low:.2f}-{range_high:.2f}]"
                                    + (f", HTF {htf_trend}" if htf_trend else "")
                                )
                            }
                            
    return None
