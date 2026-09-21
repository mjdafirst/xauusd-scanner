import requests
import config


def send_telegram_message(text):
    if "PUT_YOUR" in config.TELEGRAM_BOT_TOKEN or "PUT_YOUR" in config.TELEGRAM_CHAT_ID:
        print("[notifier] Telegram not configured yet — printing instead:\n" + text)
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": config.TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        response.raise_for_status()
        return True
    except Exception as exc:
        print(f"[notifier] Failed to send Telegram message: {exc}")
        return False


def format_signal_message(signal):
    arrow = "🟢 LONG" if signal["direction"] == "LONG" else "🔴 SHORT"
    return (f"XAUUSD Trade Idea — {arrow}\n\nEntry: ~{signal['price']:.2f}\n"
            f"Stop: {signal['stop']:.2f}\nTarget: {signal['target']:.2f}\n"
            f"Reason: {signal['reason']}\n\nVerify before trading.")
