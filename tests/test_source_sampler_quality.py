from __future__ import annotations

from ghost_protocol.application import source_sampler


def test_sample_quality_notes_warn_when_comment_sampling_is_off() -> None:
    bundle = {
        "pages": 5,
        "comments_per_post": 0,
        "items": [
            {
                "result": {
                    "raw_posts": [
                        {"title": "a", "content": "body", "comments": []},
                        {"title": "b", "content": "", "comments": []},
                    ]
                }
            }
            for _ in range(4)
        ],
    }

    notes = source_sampler.sample_quality_notes(bundle)

    assert any("댓글 샘플 수집이 꺼져 있습니다" in note for note in notes)
    assert any("게시판당 1~3페이지" in note for note in notes)
