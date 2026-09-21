"""Fetch OHLC candles from OANDA."""
import requests
import pandas as pd
import config

BASE_URLS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}
GRANULARITY_MAP = {
    "1m": "M1", "2m": "M2", "5m": "M5", "10m": "M10", "15m": "M15",
    "30m": "M30", "1h": "H1", "4h": "H4", "1d": "D",
}


def _base_url():
    return BASE_URLS.get(config.OANDA_ENVIRONMENT, BASE_URLS["practice"])


def fetch_candles(interval, count=300):
    """Return complete OANDA mid-price candles, oldest first."""
    granularity = GRANULARITY_MAP.get(interval)
    if not granularity or not config.OANDA_API_TOKEN:
        if not granularity:
            print(f"[oanda_price] No mapping for interval '{interval}'.")
        else:
            print("[oanda_price] OANDA_API_TOKEN not set.")
        return None

    url = f"{_base_url()}/v3/instruments/{config.OANDA_INSTRUMENT}/candles"
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {config.OANDA_API_TOKEN}"},
            params={"granularity": granularity, "count": count, "price": "M"},
            timeout=15,
        )
        response.raise_for_status()
        candles = response.json().get("candles", [])
    except Exception as exc:
        print(f"[oanda_price] Failed to fetch candles: {exc}")
        return None

    rows = []
    index = []
    for candle in candles:
        if candle.get("complete") is False:
            continue
        mid = candle.get("mid")
        if not mid:
            continue
        index.append(pd.to_datetime(candle["time"]))
        rows.append({
            "Open": float(mid["o"]), "High": float(mid["h"]),
            "Low": float(mid["l"]), "Close": float(mid["c"]),
            "Volume": candle.get("volume", 0),
        })
    return pd.DataFrame(rows, index=index) if rows else None
