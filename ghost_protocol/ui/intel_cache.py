"""Intel result cache helpers for the dashboard."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ghost_protocol.ui import options


INTEL_CACHE_TTL = 900
PROJECT_ROOT = Path(__file__).parents[2]
LAST_TOPIC_CACHE_PATH = PROJECT_ROOT / "last_topic_cache.json"


def cache_key(gallery_id: str, type_label: str) -> str:
    """Build the stable in-memory cache key for an intel result."""
    gallery_type = options.gallery_type_for_label(type_label)
    return f"{gallery_id}::{gallery_type}"


def cache_age_seconds(entry: dict[str, Any] | None, *, now: float | None = None) -> float | None:
    """Return cache age in seconds, or None if the entry has no timestamp."""
    if not entry or "ts" not in entry:
        return None
    base = time.time() if now is None else now
    return base - float(entry.get("ts", 0))


def is_cache_fresh(
    entry: dict[str, Any] | None,
    *,
    now: float | None = None,
    ttl: int = INTEL_CACHE_TTL,
) -> bool:
    """Check whether an intel cache entry is still usable."""
    age = cache_age_seconds(entry, now=now)
    return age is not None and age < ttl


def format_age_label(age_seconds: float) -> str:
    """Format an age value for compact Korean UI captions."""
    minutes = int(age_seconds // 60)
    seconds = int(age_seconds % 60)
    return f"{minutes}분 전" if minutes else f"{seconds}초 전"


def save_last_topic_cache(
    *,
    result: dict,
    gallery_id: str,
    type_label: str,
    path: Path = LAST_TOPIC_CACHE_PATH,
    ts: float | None = None,
) -> None:
    """Persist the latest intel result for one-click restore after restart."""
    try:
        payload = {
            "result": result,
            "gallery_id": gallery_id,
            "type_label": type_label,
            "ts": time.time() if ts is None else ts,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_last_topic_cache(path: Path = LAST_TOPIC_CACHE_PATH) -> dict | None:
    """Load the persisted intel result cache, returning None for bad files."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None
