"""Outcome-based adaptive filter and conservative SL/TP optimizer."""
import json
import os
import uuid
from datetime import datetime, timezone
import config

STOP_FACTORS = (0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
TARGET_R_VALUES = (1.3, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5)


def _default():
    return {"open_signals": [], "bucket_stats": {}, "optimizer_stats": {},
            "last_daily_summary_date": None}


def load_state():
    try:
        with open(config.LEARNING_STATE_FILE) as handle:
            state = json.load(handle)
        if isinstance(state, dict):
            state.setdefault("open_signals", [])
            state.setdefault("bucket_stats", {})
            state.setdefault("optimizer_stats", {})
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


def _optimizer_row(state, key, stop_factor, target_r):
    name = f"{key}|{stop_factor:.2f}|{target_r:.2f}"
    return state["optimizer_stats"].setdefault(name, {
        "trades": 0, "wins": 0, "losses": 0, "expectancy_sum": 0.0,
        "stop_factor": stop_factor, "target_r": target_r, "bucket": key,
    })


def _record_candidates(state, item, outcome):
    """Evaluate alternative SL/TP pairs using observed MFE/MAE excursions."""
    if outcome == "expired":
        return
    key = item["bucket_key"]
    mfe = item.get("max_favorable_r", 0.0)
    mae = item.get("max_adverse_r", 0.0)
    for stop_factor in STOP_FACTORS:
        for target_r in TARGET_R_VALUES:
            row = _optimizer_row(state, key, stop_factor, target_r)
            row["trades"] += 1
            # If both were touched in the same observed candle, assume SL first.
            hit_stop = mae >= stop_factor
            hit_target = mfe >= target_r
            if hit_stop:
                row["losses"] += 1
                row["expectancy_sum"] -= 1.0
            elif hit_target:
                row["wins"] += 1
                row["expectancy_sum"] += target_r


def _promote_if_ready(state):
    if not config.AUTO_PROMOTE:
        return
    rows = [r for r in state["optimizer_stats"].values()
            if r.get("trades", 0) >= config.MIN_VALIDATION_TRADES]
    if not rows:
        return
    # Use the aggregate result, not one lucky direction/timeframe bucket.
    grouped = {}
    for row in rows:
        pair = (row["stop_factor"], row["target_r"])
        item = grouped.setdefault(pair, {"trades": 0, "expectancy": 0.0})
        item["trades"] += row["trades"]
        item["expectancy"] += row["expectancy_sum"]
    best_pair, best = max(grouped.items(), key=lambda p: p[1]["expectancy"] / p[1]["trades"])
    best_expectancy = best["expectancy"] / best["trades"]

    current_stop = (config.ATR_STOP_MULT if config.STRATEGY_MODE != "smc"
                    else config.SMC_STOP_BUFFER_ATR_MULT)
    current_target = (config.ATR_TARGET_MULT / max(config.ATR_STOP_MULT, 1e-9)
                      if config.STRATEGY_MODE != "smc"
                      else config.MIN_RISK_REWARD)
    current_rows = [r for r in rows
                    if abs(r["stop_factor"] - 1.0) < 1e-9
                    and abs(r["target_r"] - current_target) < 1e-9]
    current_expectancy = (sum(r["expectancy_sum"] for r in current_rows) /
                          sum(r["trades"] for r in current_rows)) if current_rows else 0.0
    if best_expectancy < current_expectancy + config.MIN_IMPROVEMENT_R:
        return

    try:
        with open(config.STRATEGY_CONFIG_FILE) as handle:
            champion = json.load(handle)
    except (OSError, ValueError, TypeError):
        champion = {"version": "champion-1", "status": "champion", "parameters": {}}
    params = champion.setdefault("parameters", {})
    stop_factor, target_r = best_pair
    if config.STRATEGY_MODE == "smc":
        params["SMC_STOP_BUFFER_ATR_MULT"] = round(
            max(0.05, min(1.0, config.SMC_STOP_BUFFER_ATR_MULT * stop_factor)), 4)
        params["MIN_RISK_REWARD"] = round(max(1.1, min(4.0, target_r)), 4)
    else:
        params["ATR_STOP_MULT"] = round(max(0.5, min(3.0, config.ATR_STOP_MULT * stop_factor)), 4)
        params["ATR_TARGET_MULT"] = round(max(1.0, min(6.0, target_r * params["ATR_STOP_MULT"])), 4)
    champion["version"] = f"champion-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    champion["validation"] = {"trades": best["trades"], "expectancy_r": round(best_expectancy, 4),
                               "stop_factor": stop_factor, "target_r": target_r}
    temp = f"{config.STRATEGY_CONFIG_FILE}.tmp"
    with open(temp, "w") as handle:
        json.dump(champion, handle, indent=2)
    os.replace(temp, config.STRATEGY_CONFIG_FILE)
    print(f"[adaptive_filter] Promoted SL/TP settings: stop_factor={stop_factor}, target_R={target_r}")


def register_open_signal(signal, trend, order_result):
    if not config.LEARNING_ENABLED or not order_result:
        return None
    state = load_state()
    entry = float(signal["price"])
    risk = abs(entry - float(signal["stop"]))
    state["open_signals"].append({
        "id": str(uuid.uuid4()), "direction": signal["direction"],
        "price": entry, "stop": float(signal["stop"]), "target": float(signal["target"]),
        "initial_risk": risk, "max_favorable_r": 0.0, "max_adverse_r": 0.0,
        "bucket_key": _key(signal, trend), "age_bars": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    save_state(state)
    return state["open_signals"][-1]["id"]


def _update_excursion(item, bar):
    risk = item.get("initial_risk", 0.0)
    if risk <= 0:
        return
    if item["direction"] == "LONG":
        favorable = max(0.0, float(bar["High"]) - item["price"]) / risk
        adverse = max(0.0, item["price"] - float(bar["Low"])) / risk
    else:
        favorable = max(0.0, item["price"] - float(bar["Low"])) / risk
        adverse = max(0.0, float(bar["High"]) - item["price"]) / risk
    item["max_favorable_r"] = max(item.get("max_favorable_r", 0.0), favorable)
    item["max_adverse_r"] = max(item.get("max_adverse_r", 0.0), adverse)


def _outcome(item, bar):
    if item["direction"] == "LONG":
        stop = bar["Low"] <= item["stop"]
        target = bar["High"] >= item["target"]
    else:
        stop = bar["High"] >= item["stop"]
        target = bar["Low"] <= item["target"]
    if stop:
        return "stop"
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
        _update_excursion(item, bar)
        result = _outcome(item, bar)
        if result:
            stats = _stats(state, item["bucket_key"])
            stats["trades"] += 1
            if result == "target":
                stats["wins"] += 1
                stats["expectancy_sum"] += abs(item["target"] - item["price"]) / item["initial_risk"] if item["initial_risk"] else 0
            else:
                stats["losses"] += 1
                stats["expectancy_sum"] -= 1.0
            _record_candidates(state, item, result)
            continue
        item["age_bars"] += 1
        if item["age_bars"] >= config.MAX_SIGNAL_AGE_BARS:
            _stats(state, item["bucket_key"])["expired"] += 1
            _record_candidates(state, item, "expired")
        else:
            remaining.append(item)
    state["open_signals"] = remaining
    _promote_if_ready(state)
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
