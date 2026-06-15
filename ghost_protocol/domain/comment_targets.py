"""Comment target selection helpers.

AI-authored posts can be useful for rehearsal synergy checks, but they should
not become public self-engagement by accident.  This module therefore marks
known AI posts as simulation-only comment targets while still allowing the
generator and review package to inspect them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any


AI_COMMENT_SKIP_REASON = "ai_post_synergy_rehearsal_only"


def _post_no(value: object) -> str:
    return str(value or "").strip()


def _known_ai_set(known_ai_posts: Iterable[object] | None) -> set[str]:
    return {_post_no(item) for item in (known_ai_posts or []) if _post_no(item)}


def select_comment_target_rows(
    raw_rows: Sequence[Mapping[str, Any]] | None,
    *,
    known_ai_posts: Iterable[object] | None = None,
    limit: int = 15,
    ai_limit: int = 3,
    include_ai: bool = True,
) -> list[dict[str, Any]]:
    """Return crawl rows for comment-target context.

    Human/non-AI rows remain the main target pool.  A small number of known AI
    rows are appended and marked so the review UI can show synergy candidates
    without letting those comments publish as real engagement.
    """

    known_ai = _known_ai_set(known_ai_posts)
    human_rows: list[dict[str, Any]] = []
    ai_rows: list[dict[str, Any]] = []

    for row in raw_rows or []:
        if not isinstance(row, Mapping) or row.get("is_bot"):
            continue
        item = dict(row)
        post_no = _post_no(item.get("post_no"))
        is_ai = bool(post_no and post_no in known_ai)
        item["is_ai_post"] = is_ai
        item["comment_simulation_only"] = is_ai
        if is_ai:
            ai_rows.append(item)
        else:
            human_rows.append(item)

    limit = max(0, int(limit or 0))
    ai_limit = max(0, min(int(ai_limit or 0), limit))
    if not include_ai or ai_limit == 0:
        return human_rows[:limit]

    chosen_ai = ai_rows[:ai_limit]
    human_limit = max(0, limit - len(chosen_ai))
    return human_rows[:human_limit] + chosen_ai


def mark_target_comments(
    target_comments: Sequence[Mapping[str, Any]] | None,
    *,
    target_posts: Sequence[Mapping[str, Any]] | None = None,
    known_ai_posts: Iterable[object] | None = None,
) -> list[dict[str, Any]]:
    """Mark generated comment drafts that point at known AI-authored posts."""

    known_ai = _known_ai_set(known_ai_posts)
    for post in target_posts or []:
        if not isinstance(post, Mapping):
            continue
        post_no = _post_no(post.get("post_no"))
        if post_no and post.get("is_ai_post"):
            known_ai.add(post_no)

    marked: list[dict[str, Any]] = []
    for item in target_comments or []:
        if not isinstance(item, Mapping):
            continue
        row = dict(item)
        post_no = _post_no(row.get("post_no"))
        if post_no and post_no in known_ai:
            row["is_ai_post"] = True
            row["simulation_only"] = True
            row["skip_reason"] = AI_COMMENT_SKIP_REASON
        marked.append(row)
    return marked


def should_skip_public_comment(
    target_comment: Mapping[str, Any] | None,
    *,
    known_ai_posts: Iterable[object] | None = None,
) -> bool:
    """Return True when a comment draft must not be publicly posted."""

    if not isinstance(target_comment, Mapping):
        return False
    post_no = _post_no(target_comment.get("post_no"))
    return bool(
        target_comment.get("simulation_only")
        or target_comment.get("is_ai_post")
        or (post_no and post_no in _known_ai_set(known_ai_posts))
    )
