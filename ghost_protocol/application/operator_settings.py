"""Operator-facing publishing settings.

Keep posting controls in one place so UI defaults, workers, and tests share the
same safety and normalization rules.
"""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_PUBLIC_AI_MARKER = ""
PUBLIC_AI_DISCLOSURE_REQUIRED = False
MIN_PUBLISH_INTERVAL_MINUTES = 1
MAX_PUBLISH_INTERVAL_MINUTES = 180
DEFAULT_AI_COMMENT_WATCH_LIMIT = 5
MAX_AI_COMMENT_WATCH_LIMIT = 50

def normalize_public_ai_marker(
    marker: object,
    *,
    fallback: str = DEFAULT_PUBLIC_AI_MARKER,
) -> str:
    """Public body markers are disabled; keep the hook as a no-op shim."""

    return fallback


def normalize_publish_interval_minutes(value: object, *, default: int = 3) -> int:
    """Clamp publish interval to the UI-supported operational range."""

    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = default
    return max(MIN_PUBLISH_INTERVAL_MINUTES, min(MAX_PUBLISH_INTERVAL_MINUTES, minutes))


def normalize_ai_comment_watch_limit(value: object) -> int:
    """Clamp AI-post comment monitoring count."""

    try:
        count = int(value)
    except (TypeError, ValueError):
        count = DEFAULT_AI_COMMENT_WATCH_LIMIT
    return max(0, min(MAX_AI_COMMENT_WATCH_LIMIT, count))


@dataclass(frozen=True)
class PublishSettings:
    publish_interval_minutes: int = 3
    ai_disclosure_enabled: bool = False
    ai_disclosure_marker: str = DEFAULT_PUBLIC_AI_MARKER
    ai_comment_watch_limit: int = DEFAULT_AI_COMMENT_WATCH_LIMIT


def build_publish_settings(values: dict | object) -> PublishSettings:
    """Build normalized publish settings from a dict-like object."""

    getter = values.get if hasattr(values, "get") else lambda key, default=None: default
    return PublishSettings(
        publish_interval_minutes=normalize_publish_interval_minutes(
            getter("publish_interval_minutes", 3)
        ),
        ai_disclosure_enabled=PUBLIC_AI_DISCLOSURE_REQUIRED
        and bool(getter("ai_disclosure_enabled", PUBLIC_AI_DISCLOSURE_REQUIRED)),
        ai_disclosure_marker=normalize_public_ai_marker(
            getter("ai_disclosure_marker", DEFAULT_PUBLIC_AI_MARKER)
        ),
        ai_comment_watch_limit=normalize_ai_comment_watch_limit(
            getter("ai_comment_watch_limit", DEFAULT_AI_COMMENT_WATCH_LIMIT)
        ),
    )
