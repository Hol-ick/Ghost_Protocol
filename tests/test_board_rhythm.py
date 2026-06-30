from datetime import datetime

from ghost_protocol.domain import board_rhythm


def test_parse_post_datetime_handles_dc_formats():
    now = datetime(2026, 6, 4, 12, 0, 0)

    assert board_rhythm.parse_post_datetime("2026-06-04 11:58:30", now=now) == datetime(
        2026, 6, 4, 11, 58, 30
    )
    assert board_rhythm.parse_post_datetime("06.03", now=now) == datetime(2026, 6, 3)
    assert board_rhythm.parse_post_datetime("11:59", now=now) == datetime(2026, 6, 4, 11, 59)


def test_analyze_posting_rhythm_recommends_conservative_minutes():
    raw_posts = [
        {"post_no": "4", "title": "d", "created_at": "2026-06-04 12:00:00"},
        {"post_no": "3", "title": "c", "created_at": "2026-06-04 11:58:20"},
        {"post_no": "2", "title": "b", "created_at": "2026-06-04 11:56:40"},
        {"post_no": "1", "title": "a", "created_at": "2026-06-04 11:55:00"},
    ]

    rhythm = board_rhythm.analyze_posting_rhythm(raw_posts)

    assert rhythm["parsed_count"] == 4
    assert rhythm["interval_count"] == 3
    assert rhythm["average_seconds"] == 100
    assert rhythm["median_seconds"] == 100
    assert rhythm["recommended_minutes"] == 2
    assert rhythm["confidence"] == "low"


def test_analyze_posting_rhythm_ignores_large_page_gaps():
    raw_posts = [
        {"post_no": "3", "title": "c", "created_at": "2026-06-04 12:00:00"},
        {"post_no": "2", "title": "b", "created_at": "2026-06-04 11:59:00"},
        {"post_no": "1", "title": "a", "created_at": "2026-06-03 01:00:00"},
    ]

    rhythm = board_rhythm.analyze_posting_rhythm(raw_posts, max_gap_seconds=4 * 60 * 60)

    assert rhythm["interval_count"] == 1
    assert rhythm["average_seconds"] == 60
    assert rhythm["recommended_minutes"] == 1
