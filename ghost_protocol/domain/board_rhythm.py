"""Board posting rhythm helpers.

The crawler returns DC Inside date strings in several formats.  This module
normalizes those strings and turns recent source posts into a conservative
publish-delay recommendation.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from statistics import mean, median
from typing import Iterable


MIN_RECOMMENDED_MINUTES = 1
MAX_RECOMMENDED_MINUTES = 180


def parse_post_datetime(value: object, *, now: datetime | None = None) -> datetime | None:
    """Parse common DC Inside post time formats into a datetime."""

    raw = str(value or "").strip()
    if not raw:
        return None

    base = now or datetime.now()
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y.%m.%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y.%m.%d %H:%M",
        "%Y.%m.%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass

    match = re.match(r"^(\d{1,2})\.(\d{1,2})$", raw)
    if match:
        try:
            return datetime(base.year, int(match.group(1)), int(match.group(2)))
        except ValueError:
            return None

    match = re.match(r"^(\d{1,2}):(\d{2})$", raw)
    if match:
        try:
            parsed = datetime(
                base.year,
                base.month,
                base.day,
                int(match.group(1)),
                int(match.group(2)),
            )
        except ValueError:
            return None
        if parsed > base:
            return parsed - timedelta(days=1)
        return parsed

    return None


def _post_time(post: dict, *, now: datetime | None = None) -> datetime | None:
    for key in ("created_at", "source_created_at", "date", "time"):
        parsed = parse_post_datetime(post.get(key), now=now)
        if parsed:
            return parsed
    return None


def _trimmed(values: list[float]) -> list[float]:
    if len(values) < 5:
        return values
    ordered = sorted(values)
    trim = max(1, int(len(ordered) * 0.1))
    return ordered[trim:-trim] or ordered


def analyze_posting_rhythm(
    raw_posts: Iterable[dict] | None,
    *,
    now: datetime | None = None,
    min_gap_seconds: int = 5,
    max_gap_seconds: int = 4 * 60 * 60,
) -> dict:
    """Return posting interval statistics and a conservative minute delay."""

    posts = [post for post in list(raw_posts or []) if isinstance(post, dict)]
    timed: list[dict] = []
    for post in posts:
        parsed = _post_time(post, now=now)
        if parsed:
            timed.append(
                {
                    "post_no": str(post.get("post_no") or post.get("no") or ""),
                    "title": str(post.get("title") or post.get("source_title") or ""),
                    "created_at": str(post.get("created_at") or ""),
                    "parsed_at": parsed,
                }
            )

    timed.sort(key=lambda item: item["parsed_at"], reverse=True)
    gaps: list[float] = []
    for prev, curr in zip(timed, timed[1:]):
        gap = (prev["parsed_at"] - curr["parsed_at"]).total_seconds()
        if min_gap_seconds <= gap <= max_gap_seconds:
            gaps.append(gap)

    if not gaps:
        return {
            "sample_count": len(posts),
            "parsed_count": len(timed),
            "interval_count": 0,
            "average_seconds": None,
            "median_seconds": None,
            "trimmed_average_seconds": None,
            "recommended_minutes": None,
            "confidence": "none",
            "newest_at": timed[0]["parsed_at"].isoformat(timespec="seconds") if timed else "",
            "oldest_at": timed[-1]["parsed_at"].isoformat(timespec="seconds") if timed else "",
        }

    trimmed = _trimmed(gaps)
    avg_seconds = mean(gaps)
    median_seconds = median(gaps)
    trimmed_avg_seconds = mean(trimmed)
    recommended_minutes = int(
        min(
            MAX_RECOMMENDED_MINUTES,
            max(MIN_RECOMMENDED_MINUTES, math.ceil(trimmed_avg_seconds / 60)),
        )
    )
    if len(gaps) >= 20:
        confidence = "high"
    elif len(gaps) >= 8:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "sample_count": len(posts),
        "parsed_count": len(timed),
        "interval_count": len(gaps),
        "average_seconds": round(avg_seconds, 1),
        "median_seconds": round(median_seconds, 1),
        "trimmed_average_seconds": round(trimmed_avg_seconds, 1),
        "recommended_minutes": recommended_minutes,
        "confidence": confidence,
        "newest_at": timed[0]["parsed_at"].isoformat(timespec="seconds") if timed else "",
        "oldest_at": timed[-1]["parsed_at"].isoformat(timespec="seconds") if timed else "",
    }


def format_seconds(seconds: object) -> str:
    """Render seconds as a compact Korean duration string."""

    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "-"
    if value < 60:
        return f"{int(round(value))}초"
    minutes = value / 60
    if minutes < 60:
        return f"{minutes:.1f}분"
    return f"{minutes / 60:.1f}시간"
