"""
Smart Money Concepts (SMC) strategy: liquidity sweeps, market structure,
and Fair Value Gap (FVG) retracement entries.

Honest framing: "liquidity sweep" and "manipulation" here are pattern
labels for specific, mechanical price behavior (a wick piercing an old
high/low and closing back inside it) — not a claim about anyone's actual
intent. This is a heuristic, not a certainty. Like the breakout strategy,
its real edge (if any) can only be judged by backtesting, not by how
sophisticated the concepts sound.

Core idea, in order:
1. Find recent swing highs/lows (market structure).
2. Look for a "sweep": a wick that pierces one of those levels and closes
   back inside — a stop-hunt pattern that often precedes a reversal.
3. Require confirmation: price must have shown real momentum in the
   reversal direction since the sweep (a basic change-of-character check).
4. Find the Fair Value Gap (3-candle imbalance) left behind by that
   reversal move.
5. Only enter once price retraces back into that gap — this gives a much
   better entry price than chasing the move, which is what makes a
   positive reward:risk realistic.
6. Target the next opposing swing point (the next real liquidity in the
   market); if that's too close to clear MIN_RISK_REWARD, the signal is
   rejected rather than forced.
"""

import pandas as pd

import config
import technicals


def find_swing_points(df, left=2, right=2, lookback_bars=80):
    """
    Returns a list of confirmed swing points as dicts:
    {"idx": int, "price": float, "type": "high"|"low"}
    Only confirmed points are returned (a swing needs `right` bars after it
    to confirm, so the most recent `right` bars can never produce one yet —
    this is intentional, it avoids lookahead).
    """
    start = max(left, len(df) - lookback_bars)
    end = len(df) - right
    swings = []
    for i in range(start, end):
        window_high = df["High"].iloc[i - left: i + right + 1]
        window_low = df["Low"].iloc[i - left: i + right + 1]
        if df["High"].iloc[i] == window_high.max() and (window_high == window_high.max()).sum() == 1:
            swings.append({"idx": i, "price": df["High"].iloc[i], "type": "high"})
        if df["Low"].iloc[i] == window_low.min() and (window_low == window_low.min()).sum() == 1:
            swings.append({"idx": i, "price": df["Low"].iloc[i], "type": "low"})
    return swings


def detect_liquidity_sweep(df, swings, lookback_bars):
    """
    Looks for a recent bar whose wick pierced a swing high/low but closed
    back on the "inside" of it. Returns the most recent qualifying sweep
    as a dict, or None.
    """
    if not swings:
        return None

    recent_start = max(0, len(df) - lookback_bars)
    best = None  # most recent sweep wins if multiple qualify

    for i in range(recent_start, len(df)):
        bar = df.iloc[i]
        # Only consider swing points that existed before this bar
        prior_swings = [s for s in swings if s["idx"] < i]
        if not prior_swings:
            continue

        # Nearest prior swing low/high (most recent of each type)
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
    """
    Basic change-of-character check: since the sweep, has price actually
    shown momentum in the reversal direction? Without this, a sweep alone
    is just noise — plenty of wicks poke past old levels and go nowhere.
    """
    since = df.iloc[sweep["sweep_idx"] + 1:]
    if len(since) == 0:
        return False
    sweep_bar = df.iloc[sweep["sweep_idx"]]
    if sweep["direction"] == "LONG":
        return since["Close"].max() > sweep_bar["High"]
    else:
        return since["Close"].min() < sweep_bar["Low"]


def find_fvgs(df, start_idx, direction):
    """
    Finds Fair Value Gaps (3-candle imbalances) from start_idx onward.
    Bullish FVG: candle[i]'s high sits below candle[i+2]'s low — a gap
    the market left behind on the way up. Bearish is the mirror.
    Returns a list of {"low": float, "high": float, "formed_idx": int},
    oldest first.
    """
    fvgs = []
    end = len(df) - 2
    for i in range(start_idx, end):
        a = df.iloc[i]
        c = df.iloc[i + 2]
        if direction == "bullish" and a["High"] < c["Low"]:
            fvgs.append({"low": a["High"], "high": c["Low"], "formed_idx": i + 2})
        elif direction == "bearish" and a["Low"] > c["High"]:
            fvgs.append({"low": c["High"], "high": a["Low"], "formed_idx": i + 2})
    return fvgs


def price_in_zone(price, zone):
    return zone["low"] <= price <= zone["high"]


def find_target(swings, direction, current_price, lookback_bars_idx_floor):
    """Nearest opposing swing point beyond current price — the next real
    liquidity level the market would be reaching for."""
    if direction == "LONG":
        candidates = [s["price"] for s in swings
                      if s["type"] == "high" and s["price"] > current_price
                      and s["idx"] >= lookback_bars_idx_floor]
        return min(candidates) if candidates else None
    else:
        candidates = [s["price"] for s in swings
                      if s["type"] == "low" and s["price"] < current_price
                      and s["idx"] >= lookback_bars_idx_floor]
        return max(candidates) if candidates else None


def detect_smc_signal(df, htf_trend=None):
    """
    Same return shape as technicals.detect_signal(): a dict with
    direction/price/reason/stop/target, or None.
    """
    min_bars = max(config.SWING_LOOKBACK_BARS if hasattr(config, "SWING_LOOKBACK_BARS") else 80,
                    config.ATR_PERIOD) + 10
    if df is None or len(df) < min_bars:
        return None

    # Treat the very last row as still-forming (not yet closed), same
    # convention as technicals.py.
    closed = df.iloc[:-1].copy()
    if len(closed) < min_bars:
        return None

    ind = technicals.compute_indicators(closed)
    atr = ind["ATR"].iloc[-1]
    if pd.isna(atr) or atr <= 0:
        return None

    swings = find_swing_points(closed, left=config.SWING_LEFT, right=config.SWING_RIGHT,
                                lookback_bars=getattr(config, "SWING_LOOKBACK_BARS", 80))
    sweep = detect_liquidity_sweep(closed, swings, config.SWEEP_LOOKBACK_BARS)
    if sweep is None:
        return None

    if not confirm_momentum(closed, sweep):
        return None  # sweep happened but no real reversal momentum yet

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

    zone = None
    last_price = closed["Close"].iloc[-1]
    # Check from most recently formed backward — we want whichever
    # unfilled gap price is actually sitting in right now, not just
    # whichever formed last (price may have already moved past the most
    # recent one and be retracing into an earlier one instead).
    for candidate in reversed(fvgs):
        if price_in_zone(last_price, candidate):
            zone = candidate
            break
    if zone is None:
        return None  # sweep + reversal confirmed, but price hasn't come back to a gap yet

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

    if risk <= 0 or (reward / risk) < config.MIN_RISK_REWARD - 1e-6:
        return None  # couldn't meet the minimum reward:risk — skip rather than force it

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
