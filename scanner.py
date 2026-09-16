"""
XAUUSD Scanner — main entry point.

Runs on a loop (or once, for scheduled cloud runs): fetches price data,
the higher-timeframe trend, and the news calendar; checks for a technical
signal; suppresses it if it's a duplicate of an already-active breakout or
falls in a news blackout window; and sends a Telegram alert if a fresh,
valid signal fires.

Usage:
    python scanner.py            # runs continuously
    python scanner.py --once     # runs a single scan and exits (used by the
                                  # GitHub Actions schedule / cron)
"""

import sys
import time
from datetime import datetime

import config
import technicals
import news
import notifier
import state as state_mod


def run_once():
    print(f"\n[{datetime.now()}] Running scan...")

    df = technicals.fetch_price_data()
    htf_trend = technicals.fetch_htf_trend()
    if htf_trend:
        print(f"HTF trend: {htf_trend}")

    signal = technicals.detect_signal(df, htf_trend=htf_trend)

    if not signal:
        print("No signal this scan.")
        st = state_mod.load_state()
        st = state_mod.update_state_after_scan(None, st)
        state_mod.save_state(st)
        return

    st = state_mod.load_state()

    if not state_mod.should_alert(signal, st):
        print(f"Signal found ({signal['direction']}) but already alerted for this breakout — skipping duplicate.")
        st = state_mod.update_state_after_scan(signal, st)
        state_mod.save_state(st)
        return

    calendar_events = news.fetch_calendar()
    blackout, event = news.in_news_blackout(calendar_events)

    if blackout:
        print(f"Signal found but suppressed — inside news blackout for: {event['title']}")
        # Don't update the cooldown state here: if the blackout window
        # passes and the breakout is still live, we still want to alert once.
        return

    message = notifier.format_signal_message(signal)
    notifier.send_telegram_message(message)
    print(f"Signal sent: {signal['direction']} @ {signal['price']:.2f}")

    st = state_mod.update_state_after_scan(signal, st)
    state_mod.save_state(st)


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
