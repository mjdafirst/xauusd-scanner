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

# --- OANDA (auto-trading on a demo account) ---
# AUTO_TRADE_ENABLED is the master switch. Leave it "false" until you've
# watched alerts for a while and are ready to let the scanner place trades
# on your behalf automatically.
AUTO_TRADE_ENABLED = os.environ.get("AUTO_TRADE_ENABLED", "false").lower() == "true"

OANDA_API_TOKEN = os.environ.get("OANDA_API_TOKEN", "")
OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "")
OANDA_ENVIRONMENT = os.environ.get("OANDA_ENVIRONMENT", "practice")  # "practice" or "live"
OANDA_INSTRUMENT = "XAU_USD"

# Safety switch: even if AUTO_TRADE_ENABLED is on, the scanner refuses to
# place any order unless OANDA_ENVIRONMENT is "practice" OR this is
# explicitly set to true. This exists so a demo setup can never silently
# start trading a live account by mistake (e.g. a typo, a copy-pasted
# token, or a future you forgetting this was ever wired up).
ALLOW_LIVE_TRADING = os.environ.get("ALLOW_LIVE_TRADING", "false").lower() == "true"

# --- Position sizing ---
# Fixed size used unless USE_RISK_BASED_SIZING is on. OANDA XAU_USD units
# are roughly troy ounces — 10 units is a small, demo-appropriate size.
TRADE_UNITS = int(os.environ.get("TRADE_UNITS", "10"))

# If enabled, position size is calculated from account balance and the
# signal's stop distance instead of using a fixed size, so each trade
# risks roughly the same percentage of the account regardless of how far
# away the ATR-based stop happens to be.
USE_RISK_BASED_SIZING = os.environ.get("USE_RISK_BASED_SIZING", "false").lower() == "true"
RISK_PER_TRADE_PERCENT = float(os.environ.get("RISK_PER_TRADE_PERCENT", "1.0"))

# --- Strategy selection ---
# "smc"      = Smart Money Concepts: liquidity sweep + market structure +
#              fair value gap retracement (see smc.py)
# "breakout" = the original support/resistance breakout (see technicals.py)
STRATEGY_MODE = os.environ.get("STRATEGY_MODE", "smc")

# --- Smart Money Concepts (smc.py) parameters ---
SWING_LEFT = 2                  # bars on each side required to confirm a swing high/low
SWING_RIGHT = 2
SWEEP_LOOKBACK_BARS = 20        # how far back to look for a swing point that got swept
FVG_SEARCH_BARS = 15            # how far back to look for a qualifying fair value gap
TARGET_SEARCH_BARS = 50         # how far back to look for the nearest opposing liquidity (target)
SMC_STOP_BUFFER_ATR_MULT = 0.25 # extra buffer beyond the sweep's wick, in ATR multiples
MIN_RISK_REWARD = float(os.environ.get("MIN_RISK_REWARD", "2.0"))  # trades below this R:R are rejected

# Inverse Fair Value Gap: when a normal FVG gets fully broken through
# (price closes all the way past it), that same zone flips polarity and
# can act as a reversal zone in the opposite direction. Set to False to
# only trade FVGs in their original direction.
ENABLE_INVERSE_FVG = os.environ.get("ENABLE_INVERSE_FVG", "true").lower() == "true"

# --- News: extra-cautious window for the highest-impact event types ---
# FOMC/rate decisions tend to move gold more violently and for longer than
# an average "High" impact event, so they get a wider blackout window.
FOMC_KEYWORDS = ["fomc", "interest rate", "rate decision", "press conference", "fed chair"]
FOMC_BLACKOUT_MINUTES = int(os.environ.get("FOMC_BLACKOUT_MINUTES", "60"))

# --- News filter ---
NEWS_BLACKOUT_MINUTES = 30   # suppress signals this many minutes before/after high-impact news
NEWS_IMPACT_LEVELS = ["High"]  # which impact levels count ("High", "Medium", "Low")
FOREXFACTORY_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# --- Scan cadence ---
SCAN_INTERVAL_MINUTES = 15   # how often the scanner runs
