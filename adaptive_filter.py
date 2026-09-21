"""Conservative outcome-based adaptive filter."""
import json
import os
import uuid
from datetime import datetime, timezone
import config


def _default():
    return {"open_signals": [], "bucket_stats": {}, "last_daily_summary_date": None}


def load_state():
    try:
        with open(config.LEARNING_STATE_FILE) as handle:
            state = json.load(handle)
        if isinstance(state, dict):
            state.setdefault("open_signals", [])
            state.setdefault("bucket_stats", {})
            state.setdefault("last_daily_summary_date", None)
            return state
    except (OSError, ValueError, TypeError) as exc:
        print(f"[adaptive_filter] Failed to load state: {exc}")
    return _default()


def save_state(state):
    temp = f"{config.LEARNING_STATE_FILE}.tmp"
    with open(temp, "w") as handle:
        json.dump(state, handle, indent=2)
    os.replace(temp, config.LEARNING_STATE_FILE)


def _key(signal, trend):
    return f"{config.STRATEGY_MODE}|{signal['direction']}|{trend or 'unknown'}"


def _stats(state, key):
    return state["bucket_stats"].setdefault(key, {
        "trades": 0, "wins": 0, "losses": 0, "expired": 0,
        "expectancy_sum": 0.0,
    })


def register_open_signal(signal, trend, order_result):
    if not config.LEARNING_ENABLED or not order_result:
        return None
    state = load_state()
    state["open_signals"].append({
        "id": str(uuid.uuid4()), "direction": signal["direction"],
        "price": float(signal["price"]), "stop": float(signal["stop"]),
        "target": float(signal["target"]), "bucket_key": _key(signal, trend),
        "age_bars": 0, "created_at": datetime.now(timezone.utc).isoformat(),
    })
    save_state(state)
    return state["open_signals"][-1]["id"]


def _outcome(item, bar):
    if item["direction"] == "LONG":
        stop = bar["Low"] <= item["stop"]
        target = bar["High"] >= item["target"]
    else:
        stop = bar["High"] >= item["stop"]
        target = bar["Low"] <= item["target"]
    if stop:
        return "stop"  # conservative if both levels occur in one candle
    if target:
        return "target"
    return None


def update_open_signals(df):
    if not config.LEARNING_ENABLED or df is None or len(df) < 2:
        return
    state = load_state()
    bar = df.iloc[-2]
    remaining = []
    for item in state["open_signals"]:
        result = _outcome(item, bar)
        if result:
            stats = _stats(state, item["bucket_key"])
            stats["trades"] += 1
            risk = abs(item["price"] - item["stop"])
            if result == "target":
                stats["wins"] += 1
                stats["expectancy_sum"] += abs(item["target"] - item["price"]) / risk if risk else 0
            else:
                stats["losses"] += 1
                stats["expectancy_sum"] -= 1.0
            continue
        item["age_bars"] += 1
        if item["age_bars"] >= config.MAX_SIGNAL_AGE_BARS:
            stats = _stats(state, item["bucket_key"])
            stats["trades"] += 1
            stats["expired"] += 1
        else:
            remaining.append(item)
    state["open_signals"] = remaining
    save_state(state)


def should_block_signal(signal, trend):
    if not config.LEARNING_ENABLED:
        return False
    stats = load_state()["bucket_stats"].get(_key(signal, trend))
    if not stats or stats.get("trades", 0) < config.MIN_LEARNING_SAMPLES:
        return False
    trades = stats["trades"]
    expectancy = stats.get("expectancy_sum", 0.0) / trades
    win_rate = stats.get("wins", 0) / trades
    return expectancy <= config.LEARNING_EXPECTANCY_THRESHOLD or win_rate <= config.LEARNING_WINRATE_THRESHOLD


def summary():
    rows = []
    for key, stats in load_state()["bucket_stats"].items():
        trades = stats.get("trades", 0)
        if trades:
            rows.append(f"{key}: {trades} trades, {stats.get('wins', 0) / trades:.1%} wins, {stats.get('expectancy_sum', 0) / trades:+.2f}R")
    return "\n".join(rows) if rows else "No completed samples yet."
