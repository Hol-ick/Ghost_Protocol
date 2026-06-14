"""Process-local pacing for Gemini API calls.

The Google dashboard can show plenty of remaining quota while the app still
hits short-window 429s. This module keeps Gemini calls from piling up in the
same second across Streamlit worker threads.
"""

from __future__ import annotations

import os
import random
import threading
import time


DEFAULT_MIN_INTERVAL_SEC = 1.5
DEFAULT_JITTER_SEC = 0.5
MAX_INTERVAL_SEC = 30.0
MAX_JITTER_SEC = 10.0

_lock = threading.Lock()
_last_call_at = 0.0


def normalize_seconds(value: object, *, default: float, upper: float) -> float:
    """Convert a UI/env value to a bounded non-negative second value."""

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(float(upper), parsed))


def _env_seconds(name: str, *, default: float, upper: float) -> float:
    return normalize_seconds(os.getenv(name), default=default, upper=upper)


def configured_min_interval() -> float:
    """Return the current minimum spacing between Gemini calls."""

    return _env_seconds(
        "GEMINI_CALL_MIN_INTERVAL_SEC",
        default=DEFAULT_MIN_INTERVAL_SEC,
        upper=MAX_INTERVAL_SEC,
    )


def configured_jitter() -> float:
    """Return the current extra randomized delay applied before each call."""

    return _env_seconds(
        "GEMINI_CALL_JITTER_SEC",
        default=DEFAULT_JITTER_SEC,
        upper=MAX_JITTER_SEC,
    )


def wait_before_call(
    label: str = "",
    *,
    min_interval: float | None = None,
    jitter: float | None = None,
) -> float:
    """Sleep just enough to keep calls spaced out.

    The lock intentionally serializes concurrent Streamlit worker threads so
    draft generation, judging, and trend analysis do not burst at once.
    Returns the actual wait duration for optional debug logging.
    """

    del label  # Reserved for future per-call metrics.
    global _last_call_at

    min_interval = (
        configured_min_interval()
        if min_interval is None
        else normalize_seconds(min_interval, default=DEFAULT_MIN_INTERVAL_SEC, upper=MAX_INTERVAL_SEC)
    )
    jitter = (
        configured_jitter()
        if jitter is None
        else normalize_seconds(jitter, default=DEFAULT_JITTER_SEC, upper=MAX_JITTER_SEC)
    )

    with _lock:
        now = time.monotonic()
        wait_for_spacing = max(0.0, (_last_call_at + min_interval) - now)
        wait_for_jitter = random.uniform(0.0, jitter) if jitter > 0 else 0.0
        wait_seconds = wait_for_spacing + wait_for_jitter
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _last_call_at = time.monotonic()
        return wait_seconds


def note_rate_limit_pause(seconds: float = 60.0) -> None:
    """Push the next allowed call into the future after a 429.

    Callers often also sleep for the same backoff period before retrying. We
    store the timestamp so an immediate retry waits, while a retry after the
    caller's backoff does not pay the same cooldown twice.
    """

    global _last_call_at
    cooldown = normalize_seconds(seconds, default=60.0, upper=300.0)
    with _lock:
        _last_call_at = max(
            _last_call_at,
            time.monotonic() + cooldown - configured_min_interval(),
        )
