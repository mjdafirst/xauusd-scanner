"""
XAUUSD Scanner — main entry point.

Runs on a loop: fetches price data + news calendar, checks for a
technical signal, suppresses it if we're in a news blackout window,
and sends a Telegram alert if a valid signal fires.

Usage:
    python scanner.py            # runs continuously
    python scanner.py --once     # runs a single scan and exits (good for testing / cron)
"""

import sys
import time
from datetime import datetime

import config
import technicals
import news
import notifier


def run_once():
    print(f"\n[{datetime.now()}] Running scan...")

    df = technicals.fetch_price_data()
    signal = technicals.detect_signal(df)

    if not signal:
        print("No signal this scan.")
        return

    calendar_events = news.fetch_calendar()
    blackout, event = news.in_news_blackout(calendar_events)

    if blackout:
        print(f"Signal found but suppressed — inside news blackout for: {event['title']}")
        return

    message = notifier.format_signal_message(signal)
    notifier.send_telegram_message(message)
    print(f"Signal sent: {signal['direction']} @ {signal['price']:.2f}")


def run_forever():
    print("Starting XAUUSD scanner. Ctrl+C to stop.")
    while True:
        try:
            run_once()
        except Exception as e:
            # Never let one bad scan kill the whole loop
            print(f"[scanner] Unexpected error: {e}")
        time.sleep(config.SCAN_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        run_forever()
