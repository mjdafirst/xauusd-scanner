"""Dedicated Scanner and Auto-Trader for the 5 ICT Entry Models.

Runs every 15 minutes, evaluates Models 1-5 (FVG, BPR, IFVG, BB, and BB+FVG Confluence),
manages its own state (ict_models_state.json), and places practice orders on OANDA.
"""

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

STATE_FILE = Path("ict_models_state.json")


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
        print(f"[ict_scanner] Failed to save state: {exc}")


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
    df = technicals.fetch_price_data()
    if df is None or len(df) < 50:
        return

    trend = technicals.fetch_htf_trend()
    signal = ict_models.detect_ict_models_signal(df, htf_trend=trend)
    state = load_state()

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

    msg = f"⚡ *XAUUSD — ICT {signal['model']}*\n" + notifier.format_signal_message(signal)
    notifier.send_telegram_message(msg)

    if config.AUTO_TRADE_ENABLED:
        result = execution.place_trade(signal)
        if result is not None:
            notifier.send_telegram_message(f"ICT Order filled on OANDA practice ({config.OANDA_ENVIRONMENT}): {signal['direction']} ({signal['model']})")

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
