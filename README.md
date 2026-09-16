# XAUUSD Scanner

A rules-based scanner that watches gold (XAUUSD, via the `GC=F` futures proxy)
for technical breakout setups, filters out signals around high-impact news,
and sends trade ideas to Telegram.

## Setup — running for free on GitHub Actions (no computer needed)

This is the easiest way to run the scanner entirely from your phone —
GitHub runs it in the cloud on a schedule, no server of your own required.

1. **Create a Telegram bot** (2 minutes, free)
   - Open Telegram, message `@BotFather`
   - Send `/newbot` and follow the prompts
   - Copy the token it gives you

2. **Get your chat ID**
   - Send any message to your new bot
   - Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in your phone's browser
   - Find `"chat":{"id": ...}` in the response — that's your chat_id

3. **Create a GitHub account** (github.com) if you don't have one, and
   create a **new repository** (name it anything, e.g. `xauusd-scanner`).
   A **private** repo is recommended since this is your trading setup,
   though the token/chat_id are never stored in the code either way.

4. **Upload all these files** into the repo, keeping the folder structure:
   - `config.py`, `scanner.py`, `technicals.py`, `news.py`, `notifier.py`,
     `requirements.txt`, `README.md`
   - `.github/workflows/scan.yml` — **this exact path matters**, it's what
     tells GitHub to run the scanner on a schedule
   - On mobile: use GitHub's "Add file → Upload files" button from the repo
     page in your browser. For the `.github/workflows/scan.yml` file, you
     may need to create the folders manually — GitHub's uploader supports
     dragging a full folder structure, or you can create `scan.yml` via
     "Add file → Create new file" and type the path
     `.github/workflows/scan.yml` in the filename box, which auto-creates
     the folders.

5. **Add your Telegram credentials as secrets** (never put them directly
   in `config.py` in the repo):
   - Go to your repo → **Settings → Secrets and variables → Actions**
   - Click **New repository secret**, add:
     - Name: `TELEGRAM_BOT_TOKEN`, Value: your bot token
     - Name: `TELEGRAM_CHAT_ID`, Value: your chat id

6. **Run it**
   - Go to the **Actions** tab in your repo → select "XAUUSD Scanner" →
     **Run workflow** to trigger a manual test run immediately
   - Check the run's logs to confirm it worked, and check Telegram for the
     message (or "No signal this scan" in the logs if nothing fired)
   - After that, it runs automatically every 15 minutes on its own —
     nothing else to do

That's it — the scanner now runs continuously in the cloud and messages
your phone, with nothing installed locally.

## Setup — running on your own computer instead

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. Set your Telegram credentials as environment variables (or edit the
   fallback values directly in `config.py` for quick local testing):
   ```bash
   export TELEGRAM_BOT_TOKEN="123456:ABC-your-real-token"
   export TELEGRAM_CHAT_ID="987654321"
   ```

3. **Test it once**
   ```bash
   python scanner.py --once
   ```
   If Telegram isn't configured yet, it just prints the message to the console
   instead of failing, so you can test the logic first.

4. **Run continuously**
   ```bash
   python scanner.py
   ```
   Leave this running in a terminal, a `screen`/`tmux` session, or as a
   background service.

## How it works

- **Price data**: pulled from Yahoo Finance (`GC=F`, gold futures) every
  `SCAN_INTERVAL_MINUTES` (default 15 min). No API key required.
- **Technicals**: breakout above/below a rolling support/resistance range,
  confirmed by 20/50 EMA trend direction and filtered by RSI so it doesn't
  fire into already-overbought/oversold moves.
- **News filter**: pulls a free weekly economic calendar and suppresses
  signals within `NEWS_BLACKOUT_MINUTES` of high-impact USD/gold-relevant
  events (NFP, CPI, FOMC, etc.), since these can cause erratic price action
  that breaks technical setups.
- **Alerts**: sent to Telegram with entry, stop, target, and the reasoning
  behind the signal.

## Tuning the strategy

Everything is in `config.py`:
- `SR_LOOKBACK_BARS` — how many candles define "recent" support/resistance
- `RSI_OVERBOUGHT` / `RSI_OVERSOLD` — RSI filter thresholds
- `EMA_FAST` / `EMA_SLOW` — trend filter
- `NEWS_BLACKOUT_MINUTES` — how wide a window to avoid trading around news
- `CANDLE_INTERVAL` — timeframe (1m, 5m, 15m, 1h, etc.)

The strategy in `technicals.py` (`detect_signal`) is intentionally simple
and readable — treat it as a starting template, not a finished edge. Back-test
and paper-trade any changes before trusting it with real signals.

## Running 24/7

Options once you're happy with it:
- A cheap VPS (DigitalOcean, Linode) running `python scanner.py` inside `tmux`
- A systemd service on Linux for auto-restart
- Cron + `python scanner.py --once` every 15 minutes instead of the built-in loop

## Roadmap to auto-trading

This version only alerts. To place trades automatically later:
1. Open a broker account with an API (OANDA's REST API is a common starting
   point and has a free demo/practice environment)
2. Add an `execution.py` module that takes a `signal` dict and places an
   order via the broker's API
3. Call it from `scanner.py` in place of (or alongside) the Telegram alert
4. **Paper-trade / demo-trade extensively** before connecting to a live
   account — the signal logic here has not been back-tested or validated

## Disclaimer

This is a tool for implementing rules you choose — it is not financial advice,
and there's no guarantee any of these signals are profitable. Past performance
of any strategy (backtested or otherwise) doesn't guarantee future results.
Test thoroughly on a demo account before risking real money.
