"""Small state helpers shared by the draft worker and its regression tests."""

from __future__ import annotations

from collections.abc import Iterable


def invalidate_candidate_state(
    title: object = "",
    content: object = "",
    comments: Iterable[dict] | None = None,
) -> tuple[None, str, list[dict]]:
    """Return a terminal empty candidate so a prior retry cannot be reused.

    The arguments are intentionally accepted for call-site clarity: a failed
    retry must discard the previously observed title, body, and comments.
    """

    del title, content, comments
    return None, "", []
