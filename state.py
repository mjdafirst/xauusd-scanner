"""
Tracks whether we're currently "inside" an active breakout so we don't
re-alert every scan while price stays extended. State is saved to a JSON
file that the GitHub Actions workflow commits back to the repo, so it
persists between scheduled runs (which otherwise start from a clean
checkout each time).
"""

import json
import os

import config


def load_state():
    if not os.path.exists(config.STATE_FILE):
        return {"active_direction": None}
    try:
        with open(config.STATE_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[state] Failed to read state file, starting fresh: {e}")
        return {"active_direction": None}


def save_state(state):
    try:
        with open(config.STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"[state] Failed to write state file: {e}")


def should_alert(signal, state):
    """
    Returns True if this signal should trigger a new alert.
    A signal is only alert-worthy the first time its direction becomes
    active; while the same direction keeps re-triggering scan after scan
    (price still extended), it's suppressed until a scan comes back with
    no signal at all (breakout invalidated / pulled back), which re-arms
    the cooldown.
    """
    if signal is None:
        return False
    return state.get("active_direction") != signal["direction"]


def update_state_after_scan(signal, state):
    """Call this once per scan after checking should_alert, regardless of
    whether an alert was actually sent."""
    if signal is None:
        state["active_direction"] = None
    else:
        state["active_direction"] = signal["direction"]
    return state
