"""
Configuration for the XAUUSD scanner.

Telegram credentials are read from environment variables so they can be
stored as GitHub Actions secrets (never hardcoded/committed to the repo).
For local testing, you can instead export them in your shell:
    export TELEGRAM_BOT_TOKEN="123456:ABC..."
    export TELEGRAM_CHAT_ID="987654321"
"""

import os

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "PUT_YOUR_CHAT_ID_HERE")

# --- Data ---
TICKER = "GC=F"          # Gold futures (proxy for XAUUSD). Swap for a broker feed later if needed.
CANDLE_INTERVAL = "15m"  # yfinance interval: 1m,2m,5m,15m,30m,60m,1d ...
LOOKBACK_PERIOD = "5d"   # how much history to pull each scan

# --- Technical parameters ---
SR_LOOKBACK_BARS = 20        # bars used to define recent support/resistance
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
EMA_FAST = 20
EMA_SLOW = 50

# --- Volatility-based stops/targets ---
ATR_PERIOD = 14
ATR_STOP_MULT = 1.5    # stop = entry -/+ ATR * this multiple
ATR_TARGET_MULT = 2.5  # target = entry +/- ATR * this multiple (gives a >1:1 reward:risk)

# --- Higher-timeframe trend filter ---
# Only take a breakout if the bigger-picture trend agrees, to cut down on
# breakouts that immediately fail because they're against the larger trend.
HTF_INTERVAL = "1h"
HTF_LOOKBACK_PERIOD = "30d"

# --- Signal cooldown / state ---
# Prevents re-alerting every scan while price stays extended beyond the
# breakout level — you get one alert per breakout "episode," not one every
# 15 minutes for as long as the move continues.
STATE_FILE = "state.json"

# --- News filter ---
NEWS_BLACKOUT_MINUTES = 30   # suppress signals this many minutes before/after high-impact news
NEWS_IMPACT_LEVELS = ["High"]  # which impact levels count ("High", "Medium", "Low")
FOREXFACTORY_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# --- Scan cadence ---
SCAN_INTERVAL_MINUTES = 15   # how often the scanner runs
