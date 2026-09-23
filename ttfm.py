"""TTrades Fractal Model (TTFM) style signals: swing sweep (Candle 2),
Change in State of Delivery (CISD) confirmation, and equilibrium retracement
entry ahead of the Candle 3/4 expansion.

This is a mechanical simplification of the TTFM course concepts
(https://ttrades.com/trading-education-center/free-course/), built to slot
into this scanner alongside the existing "smc" and "breakout" modes:

1. Candle 2 closure  -> a swing high/low gets swept (a stop-hunt through
   liquidity) and price closes back inside the prior range. This reuses the
   same sweep detector as smc.py, since a TTFM Candle 2 closure and an SMC
   liquidity sweep describe the same price action.
2. CISD               -> Change in State of Delivery. We treat the open of
   the sweep candle as the "delivery" level: while price was making the
   sweep, it was still delivering in the old direction (e.g. still printing
   bearish closes into a swept low). CISD confirms only once a later candle
   closes back through that open in the new direction - proof the short-term
   delivery has actually flipped, not just wicked.
3. Equilibrium entry  -> once CISD confirms, we take the 50% level (the
   "equilibrium") of the leg from the sweep extreme to the CISD close. TTFM
   teaches that Candle 3/4 entries cluster around this midpoint before the
   next expansion leg, so the signal fires when price retraces into it.
4. Target/invalidation -> stop sits beyond the sweep extreme (the level that,
   if broken, invalidates the whole read), target is the next untouched
   opposing swing, and the trade is rejected outright if it can't clear
   MIN_RISK_REWARD - consistent with how the other strategies in this repo
   are gated.
"""

import pandas as pd

import config
import technicals
from smc import find_swing_points, detect_liquidity_sweep, find_target


def find_cisd_level(df, sweep):
    """Open of the sweep candle = the level delivery must close back through."""
    sweep_candle = df.iloc[sweep["sweep_idx"]]
    return sweep_candle["Open"]


def confirm_cisd(df, sweep, cisd_level, max_age_bars):
    """Scan forward from the sweep candle for the first close that breaks
    back through the CISD level in the trade direction. Returns the bar
    index and close price of that confirmation, or None if it hasn't
    happened yet (or took too long and the setup should be discarded).
    """
    start = sweep["sweep_idx"] + 1
    end = min(len(df), sweep["sweep_idx"] + 1 + max_age_bars)
    for i in range(start, end):
        bar = df.iloc[i]
        if sweep["direction"] == "LONG" and bar["Close"] > cisd_level:
            return {"idx": i, "close": bar["Close"]}
        if sweep["direction"] == "SHORT" and bar["Close"] < cisd_level:
            return {"idx": i, "close": bar["Close"]}
    return None


def equilibrium_zone(sweep, cisd, tolerance):
    """50% level of the leg from the sweep extreme to the CISD close, plus
    a small ATR-scaled tolerance band so the retracement doesn't have to
    tag the midpoint to the exact tick.
    """
    extreme = sweep["sweep_extreme"]
    close = cisd["close"]
    midpoint = (extreme + close) / 2
    return {"low": midpoint - tolerance, "high": midpoint + tolerance, "mid": midpoint}


def invalidated(df, sweep, cisd_idx):
    """The read is dead if price trades back through the sweep extreme
    after CISD confirmed - that's not a retracement anymore, it's a failure.
    """
    since = df.iloc[cisd_idx + 1:]
    if since.empty:
        return False
    if sweep["direction"] == "LONG":
        return since["Low"].min() < sweep["sweep_extreme"]
    return since["High"].max() > sweep["sweep_extreme"]


def detect_ttfm_signal(df, htf_trend=None):
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

    direction = sweep["direction"]
    if direction == "LONG" and htf_trend == "down":
        return None
    if direction == "SHORT" and htf_trend == "up":
        return None
    if not technicals.ttrades_context_allowed(direction, closed, htf_trend):
        return None

    cisd_level = find_cisd_level(closed, sweep)
    cisd = confirm_cisd(closed, sweep, cisd_level,
                         getattr(config, "TTFM_CISD_MAX_AGE_BARS", 15))
    if cisd is None:
        return None

    if invalidated(closed, sweep, cisd["idx"]):
        return None

    if len(closed) - 1 - cisd["idx"] > getattr(config, "TTFM_MAX_RETRACE_AGE_BARS", 20):
        return None

    tolerance = atr * getattr(config, "TTFM_EQUILIBRIUM_TOLERANCE_ATR_MULT", 0.15)
    zone = equilibrium_zone(sweep, cisd, tolerance)
    price = closed["Close"].iloc[-1]
    if not (zone["low"] <= price <= zone["high"]):
        return None

    buffer = atr * getattr(config, "TTFM_STOP_BUFFER_ATR_MULT", 0.25)
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
            f"TTFM Candle 2 sweep of {sweep['swept_level']:.2f}, CISD confirmed "
            f"at {cisd['close']:.2f}, equilibrium retracement [{zone['low']:.2f}-{zone['high']:.2f}]"
            + (f", HTF trend {htf_trend}" if htf_trend else "")
        ),
        "stop": stop,
        "target": target,
    }
