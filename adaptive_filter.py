import json
import os
import uuid
from datetime import datetime, timezone
import config


def _default():
    return {"open_signals": [], "bucket_stats": {}, "last_daily_summary_date": None}


def load_state():
    try:
        with open(config.LEARNING_STATE_FILE) as f:
            value = json.load(f)
        if isinstance(value, dict):
            value.setdefault("open_signals", []); value.setdefault("bucket_stats", {})
            value.setdefault("last_daily_summary_date", None)
            return value
    except (OSError, ValueError):
        pass
    return _default()


def save_state(state):
    with open(config.LEARNING_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _key(signal, trend):
    return f"{config.STRATEGY_MODE}|{signal['direction']}|{trend or 'unknown'}"


def register_open_signal(signal, trend, order_result):
    if not config.LEARNING_ENABLED or not order_result:
        return None
    state = load_state()
    item = {"id": str(uuid.uuid4()), "direction": signal["direction"],
            "price": float(signal["price"]), "stop": float(signal["stop"]),
            "target": float(signal["target"]), "bucket_key": _key(signal, trend),
            "age_bars": 0, "created_at": datetime.now(timezone.utc).isoformat()}
    state["open_signals"].append(item)
    save_state(state)
    return item["id"]


def _outcome(item, bar):
    long = item["direction"] == "LONG"
    stop = bar["Low"] <= item["stop"] if long else bar["High"] >= item["stop"]
    target = bar["High"] >= item["target"] if long else bar["Low"] <= item["target"]
    # Conservative tie-break: if one OHLC bar touched both levels, count stop.
    if stop: return "stop"
    if target: return "target"
    return None


def update_open_signals(df):
    if not config.LEARNING_ENABLED or df is None or len(df) < 2:
        return
    state = load_state(); remaining = []
    # Process the newest completed candle only; age represents scanner runs.
    bar = df.iloc[-2]
    for item in state["open_signals"]:
        result = _outcome(item, bar)
        if result:
            stats = state["bucket_stats"].setdefault(item["bucket_key"],
                {"trades": 0, "wins": 0, "losses": 0, "expired": 0, "expectancy_sum": 0.0})
            stats["trades"] += 1
            stats["wins"] += result == "target"; stats["losses"] += result == "stop"
            risk = abs(item["price"] - item["stop"])
            r = abs(item["target"] - item["price"]) / risk if result == "target" and risk else -1.0
            stats["expectancy_sum"] += r
        else:
            item["age_bars"] += 1
            if item["age_bars"] < config.MAX_SIGNAL_AGE_BARS:
                remaining.append(item)
            else:
                stats = state["bucket_stats"].setdefault(item["bucket_key"],
                    {"trades": 0, "wins": 0, "losses": 0, "expired": 0, "expectancy_sum": 0.0})
                stats["trades"] += 1; stats["expired"] += 1
    state["open_signals"] = remaining; save_state(state)


def should_block_signal(signal, trend):
    if not config.LEARNING_ENABLED: return False
    stats = load_state()["bucket_stats"].get(_key(signal, trend))
    if not stats or stats.get("trades", 0) < config.MIN_LEARNING_SAMPLES: return False
    n = stats["trades"]; expectancy = stats["expectancy_sum"] / n
    win_rate = stats.get("wins", 0) / n
    return expectancy <= config.LEARNING_EXPECTANCY_THRESHOLD or win_rate <= config.LEARNING_WINRATE_THRESHOLD


def summary():
    rows = []
    for key, s in load_state()["bucket_stats"].items():
        n = s.get("trades", 0)
        if n: rows.append(f"{key}: {n} trades, {s.get('wins',0)/n:.1%} wins, {s.get('expectancy_sum',0)/n:+.2f}R")
    return "\n".join(rows) if rows else "No completed samples yet."
