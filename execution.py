"""
Places trades on OANDA (demo/practice by default) based on scanner signals.

Safety notes, read before enabling:
- AUTO_TRADE_ENABLED must be explicitly turned on in config.py / env vars —
  it defaults to off, so adding OANDA credentials alone does not start
  auto-trading.
- The scanner will refuse to place ANY order if OANDA_ENVIRONMENT is not
  "practice", unless ALLOW_LIVE_TRADING is also explicitly set. This is a
  deliberate guard against accidentally trading a live account.
- Every function here catches its own exceptions and returns None on
  failure rather than raising — a broken order should never crash the
  scanner or stop it from continuing to send alerts.
"""

import requests

import config

BASE_URLS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}


def _base_url():
    return BASE_URLS.get(config.OANDA_ENVIRONMENT, BASE_URLS["practice"])


def _headers():
    return {
        "Authorization": f"Bearer {config.OANDA_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _is_configured():
    return bool(config.OANDA_API_TOKEN) and bool(config.OANDA_ACCOUNT_ID)


def get_account_balance():
    """Returns account balance as a float, or None on failure."""
    url = f"{_base_url()}/v3/accounts/{config.OANDA_ACCOUNT_ID}/summary"
    try:
        resp = requests.get(url, headers=_headers(), timeout=10)
        resp.raise_for_status()
        return float(resp.json()["account"]["balance"])
    except Exception as e:
        print(f"[execution] Failed to fetch account balance: {e}")
        return None


def calculate_units(signal):
    """
    Returns a signed unit count: positive for LONG, negative for SHORT
    (OANDA's convention — a negative unit count on a buy instrument opens
    a short position).
    """
    units = config.TRADE_UNITS

    if config.USE_RISK_BASED_SIZING:
        balance = get_account_balance()
        stop_distance = abs(signal["price"] - signal["stop"])
        if balance is not None and stop_distance > 0:
            risk_amount = balance * (config.RISK_PER_TRADE_PERCENT / 100)
            # OANDA XAU_USD: ~1 unit per troy ounce, so P&L per unit moves
            # roughly $1 for every $1 the price moves — this is an
            # approximation, not an exact margin/leverage calculation.
            units = max(1, int(risk_amount / stop_distance))
        else:
            print("[execution] Couldn't compute risk-based size, falling back to fixed TRADE_UNITS.")

    return units if signal["direction"] == "LONG" else -units


def place_trade(signal):
    """
    Places a market order on OANDA with an attached stop-loss and
    take-profit from the signal. Returns the API response dict on success,
    or None if trading is disabled, unsafe, unconfigured, or the request
    fails.
    """
    if not config.AUTO_TRADE_ENABLED:
        print("[execution] AUTO_TRADE_ENABLED is off — not placing a trade.")
        return None

    if not _is_configured():
        print("[execution] OANDA_API_TOKEN / OANDA_ACCOUNT_ID not set — not placing a trade.")
        return None

    if config.OANDA_ENVIRONMENT != "practice" and not config.ALLOW_LIVE_TRADING:
        print(
            "[execution] Refusing to trade: OANDA_ENVIRONMENT is not 'practice' "
            "and ALLOW_LIVE_TRADING is not set. This is a safety guard against "
            "accidentally trading a live account — set ALLOW_LIVE_TRADING=true "
            "only if you deliberately intend to trade real money."
        )
        return None

    units = calculate_units(signal)

    order = {
        "order": {
            "type": "MARKET",
            "instrument": config.OANDA_INSTRUMENT,
            "units": str(units),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": f"{signal['stop']:.2f}"},
            "takeProfitOnFill": {"price": f"{signal['target']:.2f}"},
        }
    }

    url = f"{_base_url()}/v3/accounts/{config.OANDA_ACCOUNT_ID}/orders"
    try:
        resp = requests.post(url, headers=_headers(), json=order, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        print(f"[execution] Order placed: {units:+d} units of {config.OANDA_INSTRUMENT} "
              f"({config.OANDA_ENVIRONMENT})")
        return data
    except Exception as e:
        print(f"[execution] Failed to place order: {e}")
        return None
