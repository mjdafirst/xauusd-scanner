"""
Sends formatted trade-idea messages to Telegram.
"""

import requests
import config


def send_telegram_message(text):
    if "PUT_YOUR" in config.TELEGRAM_BOT_TOKEN or "PUT_YOUR" in config.TELEGRAM_CHAT_ID:
        print("[notifier] Telegram not configured yet — printing instead:\n" + text)
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
        resp = requests.post(url, data=payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[notifier] Failed to send Telegram message: {e}")


def format_signal_message(signal):
    arrow = "🟢 LONG" if signal["direction"] == "LONG" else "🔴 SHORT"
    return (
        f"*XAUUSD Trade Idea* — {arrow}\n\n"
        f"*Entry:* ~{signal['price']:.2f}\n"
        f"*Stop:* {signal['stop']:.2f}\n"
        f"*Target:* {signal['target']:.2f}\n"
        f"*Reason:* {signal['reason']}\n\n"
        f"_This is a rules-based scanner alert, not financial advice. "
        f"Verify before trading._"
    )
