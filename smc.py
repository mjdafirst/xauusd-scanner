"""
Smart Money Concepts (SMC) strategy: liquidity sweeps, market structure,
and Fair Value Gap (FVG) retracement entries.

This is a mechanical pattern heuristic, not a guarantee of trading performance.
"""

import pandas as pd

import config
import technicals


def find_swing_points(df, left=2, right=2, lookback_bars=80):
    """Return confirmed swing highs and lows in the recent lookback window."""
    start = max(left, len(df) - lookback_bars)
    end = len(df) - right
    swings = []
    for i in range(start, end):
        window_high = df["High"].iloc[i - left:i + right + 1]
        window_low = df["Low"].iloc[i - left:i + right + 1]
        if (df["High"].iloc[i] == window_high.max()
                and (window_high == window_high.max()).sum() == 1):
            swings.append({"idx": i, "price": df["High"].iloc[i], "type": "high"})
        if (df["Low"].iloc[i] == window_low.min()
                and (window_low == window_low.min()).sum() == 1):
            swings.append({"idx": i, "price": df["Low"].iloc[i], "type": "low"})
    return swings


def detect_liquidity_sweep(df, swings, lookback_bars):
    """Find the most recent wick-through-and-close-back sweep."""
    if not swings:
        return None

    recent_start = max(0, len(df) - lookback_bars)
    best = None
    for i in range(recent_start, len(df)):
        bar = df.iloc[i]
        prior_swings = [s for s in swings if s["idx"] < i]
        prior_lows = [s for s in prior_swings if s["type"] == "low"]
        prior_highs = [s for s in prior_swings if s["type"] == "high"]

        if prior_lows:
            swing_low = max(prior_lows, key=lambda s: s["idx"])
            if bar["Low"] < swing_low["price"] and bar["Close"] > swing_low["price"]:
                best = {
                    "direction": "LONG",
                    "sweep_idx": i,
                    "swept_level": swing_low["price"],
                    "sweep_extreme": bar["Low"],
                }

        if prior_highs:
            swing_high = max(prior_highs, key=lambda s: s["idx"])
            if bar["High"] > swing_high["price"] and bar["Close"] < swing_high["price"]:
                best = {
                    "direction": "SHORT",
                    "sweep_idx": i,
                    "swept_level": swing_high["price"],
                    "sweep_extreme": bar["High"],
                }
    return best


def confirm_momentum(df, sweep):
    """Require a close beyond the sweep candle in the reversal direction."""
    since = df.iloc[sweep["sweep_idx"] + 1:]
    if len(since) == 0:
        return False
    sweep_bar = df.iloc[sweep["sweep_idx"]]
    if sweep["direction"] == "LONG":
        return since["Close"].max() > sweep_bar["High"]
    return since["Close"].min() < sweep_bar["Low"]


def find_fvgs(df, start_idx, direction):
    """Find bullish or bearish three-candle fair value gaps."""
    fvgs = []
    for i in range(start_idx, len(df) - 2):
        first = df.iloc[i]
        third = df.iloc[i + 2]
        if direction == "bullish" and first["High"] < third["Low"]:
            fvgs.append({"low": first["High"], "high": third["Low"], "formed_idx": i + 2})
        elif direction == "bearish" and first["Low"] > third["High"]:
            fvgs.append({"low": third["High"], "high": first["Low"], "formed_idx": i + 2})
    return fvgs


def is_fvg_unfilled(df, zone, direction, formed_idx):
    """Reject gaps invalidated by later price action."""
    for j in range(formed_idx, len(df)):
        bar = df.iloc[j]
        if direction == "bullish" and bar["Low"] <= zone["low"]:
            return False
        if direction == "bearish" and bar["High"] >= zone["high"]:
            return False
    return True


def price_in_zone(price, zone):
    return zone["low"] <= price <= zone["high"]


def find_target(swings, direction, current_price, lookback_bars_idx_floor):
    """Find the nearest opposing swing beyond the current price."""
    if direction == "LONG":
        candidates = [s["price"] for s in swings
                      if s["type"] == "high" and s["price"] > current_price
                      and s["idx"] >= lookback_bars_idx_floor]
        return min(candidates) if candidates else None

    candidates = [s["price"] for s in swings
                  if s["type"] == "low" and s["price"] < current_price
                  and s["idx"] >= lookback_bars_idx_floor]
    return max(candidates) if candidates else None


def detect_smc_signal(df, htf_trend=None):
    """Return an SMC signal with direction, entry, stop, and target, or None."""
    min_bars = max(getattr(config, "SWING_LOOKBACK_BARS", 80), config.ATR_PERIOD) + 10
    if df is None or len(df) < min_bars:
        return None

    closed = df.iloc[:-1].copy()
    if len(closed) < min_bars:
        return None

    ind = technicals.compute_indicators(closed)
    atr = ind["ATR"].iloc[-1]
    if pd.isna(atr) or atr <= 0:
        return None

    swings = find_swing_points(
        closed,
        left=config.SWING_LEFT,
        right=config.SWING_RIGHT,
        lookback_bars=getattr(config, "SWING_LOOKBACK_BARS", 80),
    )
    sweep = detect_liquidity_sweep(closed, swings, config.SWEEP_LOOKBACK_BARS)
    if sweep is None:
        return None

    if len(closed) - 1 - sweep["sweep_idx"] > getattr(config, "MAX_SWEEP_AGE_BARS", 20):
        return None
    if not confirm_momentum(closed, sweep):
        return None

    direction = sweep["direction"]
    if direction == "LONG" and htf_trend == "down":
        return None
    if direction == "SHORT" and htf_trend == "up":
        return None

    fvg_direction = "bullish" if direction == "LONG" else "bearish"
    fvg_search_start = max(sweep["sweep_idx"], len(closed) - config.FVG_SEARCH_BARS)
    fvgs = find_fvgs(closed, fvg_search_start, fvg_direction)
    if not fvgs:
        return None

    last_price = closed["Close"].iloc[-1]
    zone = None
    for candidate in reversed(fvgs):
        if (price_in_zone(last_price, candidate)
                and is_fvg_unfilled(closed, candidate, fvg_direction, candidate["formed_idx"])):
            zone = candidate
            break
    if zone is None:
        return None

    buffer = atr * config.SMC_STOP_BUFFER_ATR_MULT
    target_floor_idx = max(0, len(closed) - config.TARGET_SEARCH_BARS)

    if direction == "LONG":
        stop = sweep["sweep_extreme"] - buffer
        risk = last_price - stop
        if risk <= 0:
            return None
        target = find_target(swings, "LONG", last_price, target_floor_idx)
        min_target = last_price + risk * config.MIN_RISK_REWARD
        if target is None or target < min_target:
            target = min_target
        reward = target - last_price
    else:
        stop = sweep["sweep_extreme"] + buffer
        risk = stop - last_price
        if risk <= 0:
            return None
        target = find_target(swings, "SHORT", last_price, target_floor_idx)
        min_target = last_price - risk * config.MIN_RISK_REWARD
        if target is None or target > min_target:
            target = min_target
        reward = last_price - target

    if risk <= 0 or reward / risk < config.MIN_RISK_REWARD - 1e-6:
        return None

    return {
        "direction": direction,
        "price": last_price,
        "reason": (
            f"Liquidity sweep of {sweep['swept_level']:.2f}, momentum confirmed, "
            f"entry on FVG retracement [{zone['low']:.2f}-{zone['high']:.2f}]"
            + (f", HTF trend {htf_trend}" if htf_trend else "")
        ),
        "stop": stop,
        "target": target,
    }
