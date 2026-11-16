import requests

import config


def send_telegram_message(text):
    if "PUT_YOUR" in config.TELEGRAM_BOT_TOKEN or "PUT_YOUR" in config.TELEGRAM_CHAT_ID:
        print("[notifier] Telegram not configured yet — printing instead:\n" + text)
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": config.TELEGRAM_CHAT_ID, "text": text},
            timeout=10)
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


def format_trade_result_message(trade):
    """
    Format a Telegram message when an alerted trade reaches TP or SL.

    The result is based on candle high/low data, so if both levels were
    touched in the same candle, the bot conservatively reports stop-loss.
    """
    direction = trade.get("direction", "UNKNOWN")
    outcome = trade.get("outcome")

    if outcome == "TAKE_PROFIT":
        heading = "✅ XAUUSD TRADE HIT TAKE PROFIT"
        level_label = "Target"
    elif outcome == "STOP_LOSS":
        heading = "❌ XAUUSD TRADE HIT STOP LOSS"
        level_label = "Stop"
    else:
        heading = "⚠️ XAUUSD TRADE CLOSED"
        level_label = "Exit"

    arrow = "🟢 LONG" if direction == "LONG" else "🔴 SHORT" if direction == "SHORT" else "⚪ UNKNOWN"
    entry = float(trade["entry"])
    exit_price = float(trade["exit_price"])
    move = exit_price - entry

    return (
        f"{heading}\n\n"
        f"Direction: {arrow}\n"
        f"Entry: {entry:.2f}\n"
        f"{level_label}: {exit_price:.2f}\n"
        f"Price move: {move:+.2f} USD/oz\n\n"
        f"Opened: {trade.get('opened_at', 'unknown')}\n"
        f"Closed: {trade.get('closed_at', 'unknown')}\n\n"
        f"Reason: {trade.get('reason', 'Signal')}\n\n"
        "Candle-based result; exact intrabar fill timing is not available."
    )
