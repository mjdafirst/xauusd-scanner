import os
import json

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "PUT_YOUR_CHAT_ID_HERE")

TICKER = "GC=F"
CANDLE_INTERVAL = "5m"
LOOKBACK_PERIOD = "5d"
PRICE_SOURCE = os.environ.get("PRICE_SOURCE", "oanda")

SR_LOOKBACK_BARS = 20
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
EMA_FAST = 20
EMA_SLOW = 50
ATR_PERIOD = 14
ATR_STOP_MULT = 1.5
ATR_TARGET_MULT = 2.5
HTF_INTERVAL = "1h"
HTF_LOOKBACK_PERIOD = "30d"
STATE_FILE = "state.json"

# Demo trading remains enabled as requested. Live trading still requires the
# separate ALLOW_LIVE_TRADING switch.
AUTO_TRADE_ENABLED = os.environ.get("AUTO_TRADE_ENABLED", "true").lower() == "true"
OANDA_API_TOKEN = os.environ.get("OANDA_API_TOKEN", "")
OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "")
OANDA_ENVIRONMENT = os.environ.get("OANDA_ENVIRONMENT", "practice")
OANDA_INSTRUMENT = "XAU_USD"
ALLOW_LIVE_TRADING = os.environ.get("ALLOW_LIVE_TRADING", "false").lower() == "true"
TRADE_UNITS = int(os.environ.get("TRADE_UNITS", "10"))
USE_RISK_BASED_SIZING = os.environ.get("USE_RISK_BASED_SIZING", "false").lower() == "true"
RISK_PER_TRADE_PERCENT = float(os.environ.get("RISK_PER_TRADE_PERCENT", "1.0"))

STRATEGY_MODE = os.environ.get("STRATEGY_MODE", "smc")
SWING_LEFT = 1
SWING_RIGHT = 1
SWING_LOOKBACK_BARS = 80
SWEEP_LOOKBACK_BARS = 40
FVG_SEARCH_BARS = 25
TARGET_SEARCH_BARS = 50
MAX_SWEEP_AGE_BARS = 20
SMC_STOP_BUFFER_ATR_MULT = 0.25
MIN_RISK_REWARD = float(os.environ.get("MIN_RISK_REWARD", "1.3"))
ENABLE_INVERSE_FVG = os.environ.get("ENABLE_INVERSE_FVG", "true").lower() == "true"

# TTrades / ICT-inspired context filter. It keeps entries aligned with the
# dominant bias and prefers value zones rather than chasing price into premium.
USE_TTRADES_CONTEXT = os.environ.get("USE_TTRADES_CONTEXT", "true").lower() == "true"
TTRADES_BIAS_LOOKBACK_BARS = int(os.environ.get("TTRADES_BIAS_LOOKBACK_BARS", "80"))

FOMC_KEYWORDS = ["fomc", "interest rate", "rate decision", "press conference", "fed chair"]
FOMC_BLACKOUT_MINUTES = int(os.environ.get("FOMC_BLACKOUT_MINUTES", "60"))
NEWS_BLACKOUT_MINUTES = 30
NEWS_IMPACT_LEVELS = ["High"]
FOREXFACTORY_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
SCAN_INTERVAL_MINUTES = 15

# Adaptive optimizer controls. The optimizer only changes whitelisted strategy
# parameters and writes a versioned champion; it cannot alter execution or risk.
LEARNING_ENABLED = os.environ.get("LEARNING_ENABLED", "true").lower() == "true"
LEARNING_STATE_FILE = "learning_state.json"
MIN_LEARNING_SAMPLES = int(os.environ.get("MIN_LEARNING_SAMPLES", "20"))
LEARNING_EXPECTANCY_THRESHOLD = float(os.environ.get("LEARNING_EXPECTANCY_THRESHOLD", "-0.10"))
LEARNING_WINRATE_THRESHOLD = float(os.environ.get("LEARNING_WINRATE_THRESHOLD", "0.35"))
MAX_SIGNAL_AGE_BARS = int(os.environ.get("MAX_SIGNAL_AGE_BARS", "96"))
STRATEGY_CONFIG_FILE = os.environ.get("STRATEGY_CONFIG_FILE", "champion_strategy.json")
AUTO_PROMOTE = os.environ.get("AUTO_PROMOTE", "false").lower() == "true"
MIN_VALIDATION_TRADES = int(os.environ.get("MIN_VALIDATION_TRADES", "50"))
MIN_IMPROVEMENT_R = float(os.environ.get("MIN_IMPROVEMENT_R", "0.05"))

# Load only approved strategy parameters from the versioned champion.
_ALLOWED = {"EMA_FAST", "EMA_SLOW", "ATR_STOP_MULT", "ATR_TARGET_MULT",
            "SWEEP_LOOKBACK_BARS", "FVG_SEARCH_BARS", "MAX_SWEEP_AGE_BARS",
            "SMC_STOP_BUFFER_ATR_MULT", "MIN_RISK_REWARD"}
try:
    with open(STRATEGY_CONFIG_FILE, "r") as f:
        _candidate = json.load(f).get("parameters", {})
    for _name, _value in _candidate.items():
        if _name in _ALLOWED and isinstance(_value, (int, float)):
            globals()[_name] = _value
except (OSError, ValueError, TypeError):
    pass
