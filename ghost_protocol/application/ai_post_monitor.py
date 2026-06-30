"""Published-post review helpers.

Published posts are tracked only by the internal post-number ledger/database.
This module keeps comment review utilities and never mutates outgoing post text.
"""

from __future__ import annotations

from collections.abc import Iterable

from ghost_protocol import database
from ghost_protocol.application import operator_settings


DEFAULT_DISCLOSURE_MARKER = operator_settings.DEFAULT_PUBLIC_AI_MARKER
_MARKER_FEEDBACK_TERMS = (
    "AI",
    "ai",
    "봇",
    "인공지능",
    "GPT",
    "gpt",
    "챗GPT",
    "챗지피티",
)


def normalize_marker(marker: object) -> str:
    """Legacy compatibility shim: public body markers are disabled."""

    return ""


def apply_public_disclosure(
    title: str,
    content: str,
    *,
    enabled: bool = False,
    marker: object = DEFAULT_DISCLOSURE_MARKER,
) -> tuple[str, str]:
    """Return post text unchanged; ledger IDs are the only tracking surface."""

    return title, content


def _comment_text(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("content") or item.get("comment") or item.get("memo") or "").strip()
    return str(item or "").strip()


def _comment_author(item: object) -> str:
    return str(item.get("author") or "") if isinstance(item, dict) else ""


def _comment_created_at(item: object) -> str:
    return str(item.get("created_at") or "") if isinstance(item, dict) else ""


def classify_marker_feedback(text: str) -> tuple[bool, str]:
    """Classify comments that appear to question whether a post was automated."""

    if any(term in text for term in _MARKER_FEEDBACK_TERMS):
        return True, "자동 작성 의심/봇 언급"
    return False, ""


def record_comment_batch(
    *,
    gallery_id: str,
    post_id: str,
    comments: Iterable[object],
) -> int:
    """Persist comments found on a known AI-published post."""

    rows: list[dict] = []
    for item in comments:
        text = _comment_text(item)
        if not text:
            continue
        marker_feedback, feedback_reason = classify_marker_feedback(text)
        rows.append(
            {
                "gallery_id": str(gallery_id),
                "post_id": str(post_id),
                "author": _comment_author(item),
                "content": text,
                "created_at": _comment_created_at(item),
                "marker_feedback": int(marker_feedback),
                "feedback_reason": feedback_reason,
            }
        )
    return database.record_ai_post_comments(rows)
