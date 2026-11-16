"""
Tracks whether we're currently "inside" an active breakout so we don't
re-alert every scan while price stays extended. State is saved to a JSON
file that the GitHub Actions workflow commits back to the repo, so it
persists between scheduled runs (which otherwise start from a clean
checkout each time).

Also tracks Telegram-alerted trade ideas until their stop-loss or
take-profit level is reached, then sends one result notification.
"""

import json
import os
from datetime import datetime, timezone

import config


def load_state():
    if not os.path.exists(config.STATE_FILE):
        return {"active_direction": None, "open_trades": []}
    try:
        with open(config.STATE_FILE, "r") as f:
            state = json.load(f)
    except Exception as e:
        print(f"[state] Failed to read state file, starting fresh: {e}")
        state = {}

    state.setdefault("active_direction", None)
    state.setdefault("open_trades", [])
    if not isinstance(state["open_trades"], list):
        state["open_trades"] = []
    return state


def save_state(state):
    try:
        with open(config.STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[state] Failed to write state file: {e}")


def should_alert(signal, state):
    """
    Returns True if this signal should trigger a new alert.
    A signal is only alert-worthy the first time its direction becomes
    active; while the same direction keeps re-triggering scan after scan
    (price still extended), it's suppressed until a scan comes back with
    no signal at all (breakout invalidated / pulled back), which re-arms
    the cooldown.
    """
    if signal is None:
        return False
    return state.get("active_direction") != signal["direction"]


def update_state_after_scan(signal, state):
    """
    Call this once per scan after checking should_alert, regardless of
    whether an alert was actually sent.
    """
    if signal is None:
        state["active_direction"] = None
    else:
        state["active_direction"] = signal["direction"]
    return state


def register_alerted_trade(signal, state):
    """
    Store a Telegram-alerted trade idea for later TP/SL monitoring.

    This runs whether or not OANDA auto-trading is enabled. It records
    the idea only after a Telegram alert has been sent.
    """
    if not signal:
        return state

    trade = {
        "id": f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{signal.get('direction', 'UNKNOWN')}",
        "direction": signal.get("direction"),
        "entry": float(signal["price"]),
        "stop": float(signal["stop"]),
        "target": float(signal["target"]),
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "reason": signal.get("reason", "Signal"),
    }
    state.setdefault("open_trades", []).append(trade)
    return state


def _latest_candle(df):
    """
    Return the latest completed candle as a simple dict.

    Assumes df is ordered oldest-to-newest, as produced by the existing
    price-data functions.
    """
    if df is None or df.empty:
        return None
    last = df.iloc[-1]
    candle_time = last.get("time") if hasattr(last, "get") else last.get("time", None)
    if candle_time is not None and hasattr(candle_time, "isoformat"):
        candle_time = candle_time.isoformat()
    return {
        "time": candle_time,
        "high": float(last["high"]),
        "low": float(last["low"]),
    }


def check_open_trades(df, state):
    """
    Check each open alerted trade against the latest completed candle.

    Returns (updated_state, closed_trades).

    A trade is closed when its stop or target is touched by the candle's
    high/low. If both are touched in the same candle, stop-loss is treated
    as the conservative outcome because the exact intrabar sequence is not
    available from candle data alone.

    Because GitHub Actions scans on a schedule, the result timestamp is the
    latest observed candle, which may be later than the actual TP/SL touch.
    """
    candle = _latest_candle(df)
    open_trades = state.get("open_trades", [])
    remaining = []
    closed = []

    if candle is None:
        return state, closed

    for trade in open_trades:
        direction = trade.get("direction")
        stop = float(trade["stop"])
        target = float(trade["target"])
        high = candle["high"]
        low = candle["low"]

        if direction == "LONG":
            stop_hit = low <= stop
            target_hit = high >= target
        elif direction == "SHORT":
            stop_hit = high >= stop
            target_hit = low <= target
        else:
            remaining.append(trade)
            continue

        if stop_hit:
            result = {
                **trade,
                "outcome": "STOP_LOSS",
                "exit_price": stop,
                "closed_at": candle["time"] or datetime.now(timezone.utc).isoformat(),
            }
            closed.append(result)
        elif target_hit:
            result = {
                **trade,
                "outcome": "TAKE_PROFIT",
                "exit_price": target,
                "closed_at": candle["time"] or datetime.now(timezone.utc).isoformat(),
            }
            closed.append(result)
        else:
            remaining.append(trade)

    state["open_trades"] = remaining
    return state, closed
