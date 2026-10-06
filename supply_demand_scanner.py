"""Experimental H1 base/departure zones with M5 first-retest confirmation."""
import json
from pathlib import Path
import pandas as pd
import config, oanda_price, technicals, news, notifier, execution

STATE = Path('sd_state.json')

def detect(h, m):
    atr = technicals.compute_atr(h, 14)
    setups = []
    for end in range(15, len(h) - 3):
        a = atr.iloc[end - 1]
        if pd.isna(a) or a <= 0:
            continue
        for size in range(1, 6):
            base = h.iloc[end - size:end]
            lo, hi = float(base.Low.min()), float(base.High.max())
            if hi - lo > a:
                continue
            for j in range(end, end + 3):
                close = float(h.Close.iloc[j])
                direction = 'LONG' if close >= hi + 1.5 * a else 'SHORT' if close <= lo - 1.5 * a else None
                if direction is None:
                    continue
                ready = h.index[j] + pd.Timedelta(hours=1)
                setups.append(dict(id=f'{h.index[end-size].isoformat()}|{size}|{direction}', direction=direction, low=lo, high=hi, ready=ready))
                break
    signals = []
    for z in setups:
        future = m.loc[m.index >= z['ready']]
        if future.empty or future.index[0] > z['ready']:
            continue
        touched = False
        for timestamp, b in future.iterrows():
            long = z['direction'] == 'LONG'
            if (long and b.Low < z['low']) or (not long and b.High > z['high']):
                break
            if b.Low <= z['high'] and b.High >= z['low']:
                touched = True
            confirmed = touched and ((long and b.Close > z['high'] and b.Close > b.Open) or (not long and b.Close < z['low'] and b.Close < b.Open))
            if not confirmed:
                continue
            if timestamp != m.index[-1]:
                break
            entry = float(b.Close)
            buffer = float(technicals.compute_atr(m, 14).iloc[-1]) * 0.25
            stop = z['low'] - buffer if long else z['high'] + buffer
            risk = abs(entry - stop)
            opposing = []
            for other in setups:
                if other['ready'] > timestamp or other['direction'] == z['direction']:
                    continue
                observed = m.loc[(m.index >= other['ready']) & (m.index <= timestamp)]
                if observed.empty or observed.index[0] > other['ready']:
                    continue
                valid = observed.High.max() <= other['high'] if long else observed.Low.min() >= other['low']
                target = other['low'] if long else other['high']
                if valid and ((long and target > entry) or (not long and target < entry)):
                    opposing.append(target)
            if opposing and risk > 0:
                target = min(opposing) if long else max(opposing)
                if abs(target - entry) / risk >= 2:
                    signals.append(dict(direction=z['direction'], price=entry, stop=stop, target=target, zone_id=z['id'], reason=f'Supply/demand H1 first retest; zone {z["low"]:.2f}-{z["high"]:.2f}'))
            break
    return signals

def run():
    config.OANDA_ENVIRONMENT = 'practice'
    config.ALLOW_LIVE_TRADING = False
    h = oanda_price.fetch_candles('1h', count=300)
    m = oanda_price.fetch_candles('5m', count=5000)
    if h is None or m is None or len(m) < 30:
        raise RuntimeError('OANDA candle data unavailable; no futures fallback for execution')
    if pd.Timestamp.now(tz='UTC') - m.index[-1] > pd.Timedelta(minutes=15):
        print('Stale data; skipping')
        return
    state = json.loads(STATE.read_text()) if STATE.exists() else {'attempted': []}
    blackout, event = news.in_news_blackout(news.fetch_calendar())
    if blackout:
        print(f'News blackout: {event["title"]}')
        return
    for signal in detect(h, m):
        if signal['zone_id'] in state['attempted']:
            continue
        state['attempted'].append(signal['zone_id'])
        STATE.write_text(json.dumps(state, indent=2))
        notifier.send_telegram_message('XAUUSD SUPPLY & DEMAND\n' + notifier.format_signal_message(signal))
        result = execution.place_trade(signal)
        filled = bool(result and result.get('orderFillTransaction'))
        notifier.send_telegram_message('Supply/demand demo order filled' if filled else 'Supply/demand order not filled or trading disabled; zone will not be retried')
    print('Supply/demand scan complete')

if __name__ == '__main__':
    run()
