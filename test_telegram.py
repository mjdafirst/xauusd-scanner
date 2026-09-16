"""
Sends a one-off test message to confirm Telegram delivery is working,
without needing an actual trading signal to fire first.
"""

import config
import notifier


def main():
    if "PUT_YOUR" in config.TELEGRAM_BOT_TOKEN or "PUT_YOUR" in config.TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set.")
        return

    message = (
        "🧪 *Test message*\n\n"
        "If you're reading this, your XAUUSD Scanner bot is correctly "
        "wired up and able to send you alerts."
    )
    notifier.send_telegram_message(message)
    print("Test message sent — check Telegram.")


if __name__ == "__main__":
    main()
