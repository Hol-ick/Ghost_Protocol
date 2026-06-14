"""Read-only export helpers used by the dashboard."""

from __future__ import annotations

from ghost_protocol import database


EXPORT_HARD_LIMIT = database._EXPORT_HARD_LIMIT


def get_export_counts(gallery_id: str) -> tuple[int, int]:
    """Return post/comment row counts for a gallery export panel."""
    return (
        database.get_post_count(gallery_id),
        database.get_comment_count(gallery_id),
    )


def build_posts_csv(gallery_id: str) -> tuple[bytes, int]:
    """Build an Excel-friendly posts CSV payload."""
    return database.build_posts_csv_bytes(gallery_id)


def build_comments_csv(gallery_id: str) -> tuple[bytes, int]:
    """Build an Excel-friendly comments CSV payload."""
    return database.build_comments_csv_bytes(gallery_id)
