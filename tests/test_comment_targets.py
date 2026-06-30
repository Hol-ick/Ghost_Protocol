from ghost_protocol.domain import comment_targets


def test_select_comment_targets_includes_ai_rows_as_simulation_only() -> None:
    rows = [
        {"post_no": "1", "title": "human 1"},
        {"post_no": "2", "title": "human 2"},
        {"post_no": "99", "title": "ai post"},
        {"post_no": "3", "title": "human 3"},
    ]

    selected = comment_targets.select_comment_target_rows(
        rows,
        known_ai_posts={"99"},
        limit=3,
        ai_limit=1,
        include_ai=True,
    )

    assert len(selected) == 3
    ai_rows = [row for row in selected if row["post_no"] == "99"]
    assert ai_rows
    assert ai_rows[0]["is_ai_post"] is True
    assert ai_rows[0]["comment_simulation_only"] is True


def test_select_comment_targets_can_exclude_ai_rows() -> None:
    rows = [
        {"post_no": "1", "title": "human 1"},
        {"post_no": "99", "title": "ai post"},
    ]

    selected = comment_targets.select_comment_target_rows(
        rows,
        known_ai_posts={"99"},
        limit=10,
        include_ai=False,
    )

    assert [row["post_no"] for row in selected] == ["1"]


def test_mark_target_comments_marks_ai_targets_for_rehearsal() -> None:
    marked = comment_targets.mark_target_comments(
        [{"post_no": "99", "comment": "candidate"}],
        target_posts=[{"post_no": "99", "is_ai_post": True}],
    )

    assert marked[0]["is_ai_post"] is True
    assert marked[0]["simulation_only"] is True
    assert marked[0]["skip_reason"] == comment_targets.AI_COMMENT_SKIP_REASON


def test_public_comment_guard_skips_known_ai_posts() -> None:
    assert comment_targets.should_skip_public_comment(
        {"post_no": "99", "comment": "candidate"},
        known_ai_posts={"99"},
    )
    assert comment_targets.should_skip_public_comment(
        {"post_no": "42", "comment": "candidate", "simulation_only": True}
    )
    assert not comment_targets.should_skip_public_comment(
        {"post_no": "1", "comment": "candidate"},
        known_ai_posts={"99"},
    )
