import sys
import time
from datetime import datetime, timezone
import adaptive_filter, config, technicals, smc, news, notifier, state as state_mod, execution


def select_signal(df, trend):
    return smc.detect_smc_signal(df, htf_trend=trend) if config.STRATEGY_MODE == "smc" else technicals.detect_signal(df, htf_trend=trend)


def run_once():
    print(f"\n[{datetime.now(timezone.utc).isoformat()}] Running scan...")
    df = technicals.fetch_price_data()
    if df is None: return
    adaptive_filter.update_open_signals(df)
    trend = technicals.fetch_htf_trend()
    signal = select_signal(df, trend)
    if signal and adaptive_filter.should_block_signal(signal, trend):
        print("Signal filtered by learned bucket performance."); return
    if not signal:
        state_mod.save_state(state_mod.update_state_after_scan(None, state_mod.load_state())); return
    st = state_mod.load_state()
    if not state_mod.should_alert(signal, st): return
    blackout, event = news.in_news_blackout(news.fetch_calendar())
    if blackout:
        print(f"Signal suppressed by news: {event['title']}"); return
    notifier.send_telegram_message(notifier.format_signal_message(signal))
    result = execution.place_trade(signal)
    if result is not None:
        adaptive_filter.register_open_signal(signal, trend, result)
        notifier.send_telegram_message(f"Trade placed on OANDA {config.OANDA_ENVIRONMENT}: {signal['direction']}")
    else:
        notifier.send_telegram_message("OANDA order was not confirmed; learning record was not opened.")
    state_mod.save_state(state_mod.update_state_after_scan(signal, st))

if __name__ == "__main__":
    if "--once" in sys.argv: run_once()
    else:
        while True:
            try: run_once()
            except Exception as exc: print(f"[scanner] {exc}")
            time.sleep(config.SCAN_INTERVAL_MINUTES * 60)
