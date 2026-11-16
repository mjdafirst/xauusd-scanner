"""Format OANDA responses without mistaking acceptance for execution."""


def format_order_result(result, direction, model, account_id, environment):
    account = "***" + str(account_id)[-4:] if account_id else "not configured"
    context = f"Environment: {environment}\nAccount: {account}"
    heading = f"ICT {direction} ({model})"
    if not isinstance(result, dict):
        return (f"{heading} — FILL NOT CONFIRMED\n{context}\n"
                "No usable broker response. Check account history and Actions logs before retrying; "
                "an order may have executed despite a network error.")
    fill = result.get("orderFillTransaction")
    if (isinstance(fill, dict) and fill.get("type") == "ORDER_FILL"
            and all(fill.get(key) is not None and str(fill[key]) != ""
                    for key in ("id", "price", "units"))):
        details = [f"{heading} — FILL CONFIRMED", context,
                   f"Fill transaction: {fill['id']}",
                   f"Order ID: {fill.get('orderID', 'not supplied')}",
                   f"Actual fill price: {fill['price']}",
                   f"Filled units (signed): {fill['units']}",
                   f"Broker time: {fill.get('time', 'not supplied')}"]
        opened = fill.get("tradeOpened")
        if isinstance(opened, dict) and opened.get("tradeID"):
            details.append(f"Opened trade ID: {opened['tradeID']}")
        else:
            details.append("No new trade ID reported; fill may reduce or close an existing position.")
        details.append("This confirms execution, not a TP/SL outcome.")
        return "\n".join(details)
    for key, label in (("orderRejectTransaction", "REJECTED"),
                       ("orderCancelTransaction", "CANCELLED")):
        transaction = result.get(key)
        if isinstance(transaction, dict):
            reason = transaction.get("rejectReason") or transaction.get("reason") or "not supplied"
            return (f"{heading} — {label}\n{context}\n"
                    f"Transaction: {transaction.get('id', 'not supplied')}\nReason: {reason}\n"
                    "No fill confirmed by this response.")
    return (f"{heading} — FILL NOT CONFIRMED\n{context}\n"
            "Response contains no complete ORDER_FILL transaction. "
            "Check account history and Actions logs before retrying.")
