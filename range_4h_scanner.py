"""Independent Scanner for 4H Range Scalping (Fakeout & Re-entry).

Runs on its own schedule, tracks its own cooldown state (range_4h_state.json),
and sends labeled Telegram alerts without interfering with the main scanner.
"""

import sys
import time
from datetime import datetime, timezone
import json
from pathlib import Path
import config
import technicals
import range_4h
import news
import notifier
import execution

STATE_FILE = Path("range_4h_state.json")


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_alert_direction": None, "last_alert_time": None}


def save_state(state):
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as exc:
        print(f"[range_4h_scanner] Failed to save state: {exc}")


def should_alert(signal, state):
    if signal is None:
        return False
    # Avoid repeating identical alert for the same day/session
    last_dir = state.get("last_alert_direction")
    last_time = state.get("last_alert_time")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if last_dir == signal["direction"] and last_time == now_str:
        return False
    return True


def run_once():
    print(f"\n[{datetime.now(timezone.utc).isoformat()}] Running 4H Range Scan...")
    df = technicals.fetch_price_data()
    if df is None or len(df) < 50:
        return

    trend = technicals.fetch_htf_trend()
    signal = range_4h.detect_range_4h_signal(df, htf_trend=trend)
    state = load_state()

    if not signal:
        print("[range_4h_scanner] No setup currently.")
        return

    if not should_alert(signal, state):
        print(f"[range_4h_scanner] Signal suppressed by daily cooldown ({signal['direction']}).")
        return

    # Check news blackout
    blackout, event = news.in_news_blackout(news.fetch_calendar())
    if blackout:
        print(f"[range_4h_scanner] Signal suppressed by news: {event['title']}")
        return

    # Send dedicated Telegram alert
    msg = f"🔔 *XAUUSD — 4H RANGE SCALPING*\n" + notifier.format_signal_message(signal)
    notifier.send_telegram_message(msg)

    # Optional demo auto-trading
    if config.AUTO_TRADE_ENABLED:
        result = execution.place_trade(signal)
        if result is not None:
            notifier.send_telegram_message(f"4H Range trade placed on OANDA ({config.OANDA_ENVIRONMENT}): {signal['direction']}")

    # Update state
    state["last_alert_direction"] = signal["direction"]
    state["last_alert_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    save_state(state)


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        while True:
            try:
                run_once()
            except Exception as exc:
                print(f"[range_4h_scanner] {exc}")
            time.sleep(config.SCAN_INTERVAL_MINUTES * 60)
