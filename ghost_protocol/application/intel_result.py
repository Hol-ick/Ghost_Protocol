"""Validation and usage rules for a completed trend-analysis result."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


class TrendPayloadError(ValueError):
    """Raised when a syntactically valid LLM response breaks the trend contract."""

    def __init__(self, message: str, *, reason: str = "invalid_trend_payload") -> None:
        super().__init__(message)
        self.reason = reason


_REQUIRED_KEYS = frozenset(
    {
        "hot_topics",
        "sentiment",
        "memes",
        "summary",
        "ai_analysis",
        "generation_guidance",
    }
)
_MODEL_REQUIRED_KEYS = frozenset(
    {
        "hot_topics",
        "sentiment",
        "memes",
        "topic_slots",
        "ai_analysis",
        "generation_guidance",
    }
)
_SUMMARY_PATTERN = re.compile(
    r"^\[A:\s*[^\[\]\r\n]{1,48}\]\s*/\s*"
    r"\[B:\s*[^\[\]\r\n]{1,48}\]\s*/\s*"
    r"\[C:\s*[^\[\]\r\n]{1,48}\]$"
)


def is_parse_failed(result: Mapping[str, Any] | None) -> bool:
    """Return whether the result is diagnostic-only and must not drive drafting."""

    return bool(result and result.get("_parse_error"))


def can_seed_generation(result: Mapping[str, Any] | None) -> bool:
    """Return whether an Intel result is safe to use as a draft topic source."""

    if not result or is_parse_failed(result):
        return False
    return bool(
        "".join(
            str(result.get(key) or "").strip()
            for key in ("ai_analysis", "generation_guidance", "summary")
        )
    )


def _validate_short_string(value: object, *, key: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip():
        raise TrendPayloadError(f"{key} must be a non-empty string")
    if len(value.strip()) > maximum:
        raise TrendPayloadError(f"{key} exceeds {maximum} characters")


def _validate_string_list(value: object, *, key: str, maximum_items: int) -> None:
    if not isinstance(value, list) or not value or len(value) > maximum_items:
        raise TrendPayloadError(f"{key} must contain 1..{maximum_items} items")
    for item in value:
        _validate_short_string(item, key=key, maximum=72)


def validate_trend_payload(payload: Mapping[str, Any]) -> None:
    """Reject complete JSON that is too large or violates the A/B/C slot contract."""

    if not isinstance(payload, Mapping):
        raise TrendPayloadError("trend payload must be an object")
    missing = _REQUIRED_KEYS.difference(payload)
    if missing:
        raise TrendPayloadError(f"trend payload missing keys: {', '.join(sorted(missing))}")

    _validate_string_list(payload.get("hot_topics"), key="hot_topics", maximum_items=4)
    memes = payload.get("memes")
    if not isinstance(memes, list) or len(memes) > 4:
        raise TrendPayloadError("memes must contain at most 4 items")
    for item in memes:
        _validate_short_string(item, key="memes", maximum=72)
    _validate_short_string(payload.get("sentiment"), key="sentiment", maximum=24)
    _validate_short_string(payload.get("ai_analysis"), key="ai_analysis", maximum=520)
    _validate_short_string(payload.get("generation_guidance"), key="generation_guidance", maximum=420)

    summary = payload.get("summary")
    _validate_short_string(summary, key="summary", maximum=180)
    if not _SUMMARY_PATTERN.fullmatch(str(summary).strip()):
        raise TrendPayloadError("summary must contain exactly A/B/C slots")


def normalize_trend_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Convert the model's label-free topic list into the legacy summary string.

    Small local models tend to continue literal ``[A]``/``[B]`` labels when
    asked to emit the old summary format.  The model therefore returns exactly
    three plain topic strings; code, not the model, owns the presentation
    labels consumed by the older UI and draft pipeline.
    """

    if not isinstance(payload, Mapping):
        raise TrendPayloadError("trend payload must be an object")

    # Old cache entries and an already-running worker can still return the
    # previous summary string contract.  Validate and preserve those entries;
    # only fresh model calls are asked for topic_slots.
    if "topic_slots" not in payload:
        validate_trend_payload(payload)
        return dict(payload)

    missing = _MODEL_REQUIRED_KEYS.difference(payload)
    if missing:
        raise TrendPayloadError(
            f"trend model payload missing keys: {', '.join(sorted(missing))}"
        )

    slots = payload.get("topic_slots")
    if not isinstance(slots, list) or len(slots) != 3:
        raise TrendPayloadError("topic_slots must contain exactly 3 items")
    for slot in slots:
        _validate_short_string(slot, key="topic_slots", maximum=48)
        if any(marker in slot for marker in ("[", "]", "\n", "\r")):
            raise TrendPayloadError("topic_slots must be plain single-line phrases")

    normalized = dict(payload)
    normalized.pop("topic_slots", None)
    normalized["summary"] = " / ".join(
        f"[{label}: {str(slot).strip()}]"
        for label, slot in zip(("A", "B", "C"), slots, strict=True)
    )
    validate_trend_payload(normalized)
    return normalized
