"""Read-only broker exit checks for newly confirmed ICT trades.

Persist state after polling. Delivery is at-least-once: a crash after Telegram
acceptance but before durable state persistence can cause a duplicate.
"""
import hashlib
import requests
import config
import execution


def scope():
    value = f"{config.OANDA_ENVIRONMENT}:{config.OANDA_ACCOUNT_ID}"
    return hashlib.sha256(value.encode()).hexdigest()


def register_fill(result, signal, state):
    fill = result.get("orderFillTransaction", {}) if isinstance(result, dict) else {}
    opened = fill.get("tradeOpened", {})
    if fill.get("type") != "ORDER_FILL" or not isinstance(opened, dict) or not opened.get("tradeID"):
        return
    key = scope() + ":" + str(opened["tradeID"])
    state.setdefault("broker_trades", {}).setdefault(key, {
        "trade_id": str(opened["tradeID"]), "scope": scope(),
        "direction": signal["direction"], "model": signal.get("model", "ICT"),
    })


def get_json(path):
    if config.OANDA_ENVIRONMENT not in execution.BASE_URLS:
        raise ValueError("Unknown broker environment")
    url = (execution.BASE_URLS[config.OANDA_ENVIRONMENT]
           + f"/v3/accounts/{config.OANDA_ACCOUNT_ID}/" + path)
    response = requests.get(url, headers=execution._headers(), timeout=15)
    response.raise_for_status()
    return response.json()


def closure_message(record, trade, transaction):
    if trade.get("state") != "CLOSED":
        raise ValueError("Trade not fully closed")
    if transaction.get("type") != "ORDER_FILL":
        raise ValueError("Exit is not an ORDER_FILL")
    closed = transaction.get("tradesClosed", [])
    if not any(str(item.get("tradeID")) == record["trade_id"] for item in closed):
        raise ValueError("Closing transaction does not close the tracked trade")
    reason = transaction.get("reason", "UNKNOWN")
    label = {"TAKE_PROFIT_ORDER": "TAKE PROFIT",
             "STOP_LOSS_ORDER": "STOP LOSS",
             "GUARANTEED_STOP_LOSS_ORDER": "GUARANTEED STOP LOSS",
             "TRAILING_STOP_LOSS_ORDER": "TRAILING STOP LOSS"}.get(reason, "OTHER CLOSE")
    account = "***" + str(config.OANDA_ACCOUNT_ID)[-4:]
    return (f"OANDA BROKER-CONFIRMED {label}\n"
            f"XAU_USD {record['direction']} — {record['model']}\n"
            f"Environment: {config.OANDA_ENVIRONMENT}\nAccount: {account}\n"
            f"Trade ID: {record['trade_id']}\n"
            f"Closing transaction: {transaction['id']}\n"
            f"Broker reason: {reason}\n"
            f"Entry: {trade.get('price', 'not supplied')}\n"
            f"Final fill price: {transaction.get('price', 'not supplied')}\n"
            f"Average close price: {trade.get('averageClosePrice', 'not supplied')}\n"
            f"Trade realized P/L: {trade.get('realizedPL', 'not supplied')} (account currency)\n"
            f"Financing: {trade.get('financing', 'not supplied')} (account currency)\n"
            f"Broker close time: {trade.get('closeTime', 'not supplied')}\n"
            "Fully closed trade; final exit reason shown. Realized P/L is not an all-fees net figure.")


def poll(state, send, fetch=None):
    if not config.OANDA_API_TOKEN or not config.OANDA_ACCOUNT_ID:
        return
    fetch = fetch or get_json
    records = state.setdefault("broker_trades", {})
    for key, record in list(records.items()):
        if record.get("scope") != scope():
            continue
        try:
            if "pending_message" not in record:
                trade = fetch(f"trades/{record['trade_id']}")["trade"]
                if str(trade.get("id")) != record["trade_id"] or trade.get("instrument") != "XAU_USD":
                    raise ValueError("Broker trade identity mismatch")
                if trade.get("state") != "CLOSED":
                    continue
                ids = trade.get("closingTransactionIDs", [])
                if not ids:
                    raise ValueError("Closed trade has no closing transaction IDs")
                transaction = fetch(f"transactions/{max(ids, key=int)}")["transaction"]
                record["pending_message"] = closure_message(record, trade, transaction)
            if send(record["pending_message"]):
                del records[key]
        except Exception as exc:
            # Avoid printing credentials, URLs, or broker payloads in public logs.
            print(f"[broker_exits] Trade {record.get('trade_id')}: check deferred ({type(exc).__name__})")
