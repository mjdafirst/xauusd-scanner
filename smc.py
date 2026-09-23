"""Mechanical SMC-style liquidity sweep and FVG retracement signals."""

import pandas as pd

import config
import technicals


def find_swing_points(df, left=2, right=2, lookback_bars=80):
    start = max(left, len(df) - lookback_bars)
    end = len(df) - right
    swings = []
    for i in range(start, end):
        highs = df["High"].iloc[i - left:i + right + 1]
        lows = df["Low"].iloc[i - left:i + right + 1]
        if df["High"].iloc[i] == highs.max() and (highs == highs.max()).sum() == 1:
            swings.append({"idx": i, "price": df["High"].iloc[i], "type": "high"})
        if df["Low"].iloc[i] == lows.min() and (lows == lows.min()).sum() == 1:
            swings.append({"idx": i, "price": df["Low"].iloc[i], "type": "low"})
    return swings


def detect_liquidity_sweep(df, swings, lookback_bars):
    best = None
    for i in range(max(0, len(df) - lookback_bars), len(df)):
        bar = df.iloc[i]
        prior = [s for s in swings if s["idx"] < i]
        lows = [s for s in prior if s["type"] == "low"]
        highs = [s for s in prior if s["type"] == "high"]
        if lows:
            level = max(lows, key=lambda s: s["idx"])
            if bar["Low"] < level["price"] and bar["Close"] > level["price"]:
                best = {"direction": "LONG", "sweep_idx": i,
                        "swept_level": level["price"], "sweep_extreme": bar["Low"]}
        if highs:
            level = max(highs, key=lambda s: s["idx"])
            if bar["High"] > level["price"] and bar["Close"] < level["price"]:
                best = {"direction": "SHORT", "sweep_idx": i,
                        "swept_level": level["price"], "sweep_extreme": bar["High"]}
    return best


def confirm_momentum(df, sweep):
    since = df.iloc[sweep["sweep_idx"] + 1:]
    if since.empty:
        return False
    bar = df.iloc[sweep["sweep_idx"]]
    if sweep["direction"] == "LONG":
        return since["Close"].max() > bar["High"]
    return since["Close"].min() < bar["Low"]


def find_fvgs(df, start_idx, direction):
    fvgs = []
    for i in range(start_idx, len(df) - 2):
        first, third = df.iloc[i], df.iloc[i + 2]
        if direction == "bullish" and first["High"] < third["Low"]:
            fvgs.append({"low": first["High"], "high": third["Low"], "formed_idx": i + 2})
        elif direction == "bearish" and first["Low"] > third["High"]:
            fvgs.append({"low": third["High"], "high": first["Low"], "formed_idx": i + 2})
    return fvgs


def is_fvg_unfilled(df, zone, direction, formed_idx):
    for i in range(formed_idx, len(df)):
        if direction == "bullish" and df.iloc[i]["Low"] <= zone["low"]:
            return False
        if direction == "bearish" and df.iloc[i]["High"] >= zone["high"]:
            return False
    return True


def find_target(swings, direction, current_price, floor):
    if direction == "LONG":
        values = [s["price"] for s in swings if s["type"] == "high" and s["price"] > current_price and s["idx"] >= floor]
        return min(values) if values else None
    values = [s["price"] for s in swings if s["type"] == "low" and s["price"] < current_price and s["idx"] >= floor]
    return max(values) if values else None


def detect_smc_signal(df, htf_trend=None):
    min_bars = max(getattr(config, "SWING_LOOKBACK_BARS", 80), config.ATR_PERIOD) + 10
    if df is None or len(df) < min_bars:
        return None
    closed = df.iloc[:-1].copy()
    if len(closed) < min_bars:
        return None

    indicators = technicals.compute_indicators(closed)
    atr = indicators["ATR"].iloc[-1]
    if pd.isna(atr) or atr <= 0:
        return None

    swings = find_swing_points(closed, config.SWING_LEFT, config.SWING_RIGHT,
                               getattr(config, "SWING_LOOKBACK_BARS", 80))
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
    if not technicals.ttrades_context_allowed(direction, closed, htf_trend):
        return None

    fvg_direction = "bullish" if direction == "LONG" else "bearish"
    fvg_start = max(sweep["sweep_idx"], len(closed) - config.FVG_SEARCH_BARS)
    price = closed["Close"].iloc[-1]
    zone = None
    for candidate in reversed(find_fvgs(closed, fvg_start, fvg_direction)):
        if (candidate["low"] <= price <= candidate["high"]
                and is_fvg_unfilled(closed, candidate, fvg_direction, candidate["formed_idx"])):
            zone = candidate
            break
    if zone is None:
        return None

    buffer = atr * config.SMC_STOP_BUFFER_ATR_MULT
    floor = max(0, len(closed) - config.TARGET_SEARCH_BARS)
    if direction == "LONG":
        stop = sweep["sweep_extreme"] - buffer
        risk = price - stop
        if risk <= 0:
            return None
        target = find_target(swings, direction, price, floor)
        minimum = price + risk * config.MIN_RISK_REWARD
        target = minimum if target is None or target < minimum else target
        reward = target - price
    else:
        stop = sweep["sweep_extreme"] + buffer
        risk = stop - price
        if risk <= 0:
            return None
        target = find_target(swings, direction, price, floor)
        minimum = price - risk * config.MIN_RISK_REWARD
        target = minimum if target is None or target > minimum else target
        reward = price - target

    if reward / risk < config.MIN_RISK_REWARD - 1e-6:
        return None

    return {
        "direction": direction,
        "price": price,
        "reason": (
            f"Liquidity sweep of {sweep['swept_level']:.2f}, momentum confirmed, "
            f"FVG retracement [{zone['low']:.2f}-{zone['high']:.2f}], value context"
            + (f", HTF trend {htf_trend}" if htf_trend else "")
        ),
        "stop": stop,
        "target": target,
    }
