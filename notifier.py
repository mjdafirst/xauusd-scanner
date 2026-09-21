"""
Fetches OHLC candles directly from OANDA for XAU_USD, so the scanner works
off the same price OANDA would actually fill your trades at — removing the
gap between GC=F futures and real spot XAUUSD.

Returns data in the same shape technicals.py expects (a DataFrame with
Open/High/Low/Close/Volume columns, oldest first), so it's a drop-in
replacement for the yfinance path.
"""

import requests
import pandas as pd

import config

BASE_URLS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}

# Maps this project's interval strings to OANDA's granularity codes.
GRANULARITY_MAP = {
    "1m": "M1", "2m": "M2", "5m": "M5", "10m": "M10", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D",
}


def _base_url():
    return BASE_URLS.get(config.OANDA_ENVIRONMENT, BASE_URLS["practice"])


def _headers():
    return {"Authorization": f"Bearer {config.OANDA_API_TOKEN}"}


def fetch_candles(interval, count=300):
    """
    Returns a DataFrame of the most recent `count` complete candles at the given
    interval, or None on any failure (missing token, bad interval, request
    error) so callers can fall back to another data source.

    The last candle from OANDA is often still incomplete. We ignore
    incomplete candles to keep the DataFrame aligned with the rest of the
    codebase, which already treats the newest row as 'not yet closed'.
    """
    granularity = GRANULARITY_MAP.get(interval)
    if not granularity:
        print(f"[oanda_price] No OANDA granularity mapping for interval '{interval}'.")
        return None

    if not config.OANDA_API_TOKEN:
        print("[oanda_price] OANDA_API_TOKEN not set — can't fetch OANDA price data.")
        return None

    url = f"{_base_url()}/v3/instruments/{config.OANDA_INSTRUMENT}/candles"
    params = {"granularity": granularity, "count": count, "price": "M"}  # mid price

    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=15)
        resp.raise_for_status()
        candles = resp.json().get("candles", [])
    except Exception as e:
        print(f"[oanda_price] Failed to fetch candles: {e}")
        return None

    if not candles:
        return None

    rows, idx = [], []
    for c in candles:
        if c.get("complete") is False:
            continue
        mid = c.get("mid")
        if not mid:
            continue
        idx.append(pd.to_datetime(c["time"]))
        rows.append({
            "Open": float(mid["o"]),
            "High": float(mid["h"]),
            "Low": float(mid["l"]),
            "Close": float(mid["c"]),
            "Volume": c.get("volume", 0),
        })

    if not rows:
        return None

    return pd.DataFrame(rows, index=idx)
