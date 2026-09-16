"""
Fetches upcoming/recent high-impact economic news events and checks
whether we're currently inside a "news blackout" window.
"""

import requests
from datetime import datetime, timedelta, timezone

import config


def fetch_calendar():
    """
    Pulls this week's economic calendar (free, no API key).
    Returns a list of dicts like:
      {"title": "Non-Farm Payrolls", "country": "USD", "date": datetime, "impact": "High"}
    Returns [] on any failure (network issue, format change, etc.) so the
    scanner degrades gracefully instead of crashing.
    """
    try:
        resp = requests.get(config.FOREXFACTORY_CALENDAR_URL, timeout=10)
        resp.raise_for_status()
        raw_events = resp.json()
    except Exception as e:
        print(f"[news] Failed to fetch calendar: {e}")
        return []

    events = []
    for item in raw_events:
        try:
            # Feed format: {"title":..., "country":..., "date":"2026-09-16T12:30:00-04:00", "impact":"High", ...}
            event_time = datetime.fromisoformat(item["date"])
            events.append({
                "title": item.get("title", "Unknown event"),
                "country": item.get("country", ""),
                "date": event_time,
                "impact": item.get("impact", ""),
            })
        except Exception:
            continue  # skip malformed entries rather than failing the whole batch

    return events


def relevant_events(events):
    """Filter to gold-relevant currencies and configured impact levels."""
    gold_relevant_ccy = {"USD", "XAU", "EUR", "GBP"}  # USD moves gold most; others add context
    return [
        e for e in events
        if e["country"] in gold_relevant_ccy and e["impact"] in config.NEWS_IMPACT_LEVELS
    ]


def in_news_blackout(events, now=None):
    """
    Returns (bool, event_or_None) — True if `now` falls within
    NEWS_BLACKOUT_MINUTES of any relevant event.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    window = timedelta(minutes=config.NEWS_BLACKOUT_MINUTES)

    for e in relevant_events(events):
        event_time = e["date"]
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
        if abs((now - event_time)) <= window:
            return True, e

    return False, None
