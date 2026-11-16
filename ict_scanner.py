"""Dedicated scanner for ICT entry models; reports verified broker fills and exits."""

import sys
import time
from datetime import datetime, timezone
import json
from pathlib import Path
import config
import technicals
import ict_models
import news
import notifier
import execution
import broker_exits
from order_feedback import format_order_result

STATE_FILE = Path("ict_models_state.json")


def load_state():
    if STATE_FILE.exists():
        # Fail closed on corrupt state rather than forgetting tracked trades.
        data = json.loads(STATE_FILE.read_text())
        if not isinstance(data, dict):
            raise ValueError("ICT state must be an object")
        return data
    return {"last_alert_direction": None, "last_alert_time": None}


def save_state(state):
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2))
    temporary.replace(STATE_FILE)


def should_alert(signal, state):
    if signal is None:
        return False
    last_dir = state.get("last_alert_direction")
    last_time = state.get("last_alert_time")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H")
    if last_dir == signal["direction"] and last_time == now_str:
        return False
    return True


def run_once():
    print(f"\n[{datetime.now(timezone.utc).isoformat()}] Running ICT 5 Models Scan...")
    state = load_state()
    broker_exits.poll(state, notifier.send_telegram_message)
    save_state(state)
    df = technicals.fetch_price_data()
    if df is None or len(df) < 50:
        return

    trend = technicals.fetch_htf_trend()
    signal = ict_models.detect_ict_models_signal(df, htf_trend=trend)

    if not signal:
        print("[ict_scanner] No ICT model setup currently.")
        return

    if not should_alert(signal, state):
        print(f"[ict_scanner] Signal suppressed by cooldown ({signal['direction']}).")
        return

    blackout, event = news.in_news_blackout(news.fetch_calendar())
    if blackout:
        print(f"[ict_scanner] Suppressed by news: {event['title']}")
        return

    msg = f"ICT {signal['model']}\n" + notifier.format_signal_message(signal)
    notifier.send_telegram_message(msg)

    if config.AUTO_TRADE_ENABLED:
        result = execution.place_trade(signal)
        broker_exits.register_fill(result, signal, state)
        # Persist broker IDs before confirmation delivery or subsequent work.
        state["last_alert_direction"] = signal["direction"]
        state["last_alert_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H")
        save_state(state)
        feedback = format_order_result(
            result, signal["direction"], signal["model"],
            config.OANDA_ACCOUNT_ID, config.OANDA_ENVIRONMENT)
        print(f"[ict_scanner] {feedback}")
        notifier.send_telegram_message(feedback)
    else:
        notifier.send_telegram_message("ICT alert only: automatic trading is disabled; no order submitted.")

    state["last_alert_direction"] = signal["direction"]
    state["last_alert_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H")
    save_state(state)


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        while True:
            try:
                run_once()
            except Exception as exc:
                print(f"[ict_scanner] {exc}")
            time.sleep(config.SCAN_INTERVAL_MINUTES * 60)
