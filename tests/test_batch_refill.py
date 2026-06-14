from ghost_protocol.domain import batch_refill


def test_merge_valid_scripts_discards_failures_and_duplicates():
    merged = batch_refill.merge_valid_scripts(
        [{"title": "A", "content": "a", "_failed": False}],
        [
            {"title": "A", "content": "a", "_failed": False},
            {"title": "", "content": "", "_failed": True},
            {"title": "B", "content": "b", "_failed": False},
        ],
        target_count=3,
    )

    assert [item["title"] for item in merged] == ["A", "B"]
    assert batch_refill.missing_count(merged, 3) == 1


def test_renumber_scripts_is_contiguous():
    scripts = batch_refill.renumber_scripts(
        [
            {"wave": 2, "title": "A", "content": "a"},
            {"wave": 8, "title": "B", "content": "b"},
        ]
    )

    assert [item["wave"] for item in scripts] == [1, 2]
