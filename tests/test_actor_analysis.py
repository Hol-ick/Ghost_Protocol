from __future__ import annotations

from ghost_protocol.domain import actor_analysis


def test_analyze_actors_groups_posts_by_public_identity() -> None:
    result = actor_analysis.analyze_actors(
        [
            {
                "post_no": "10",
                "title": "목성 중력 얘기",
                "content": "먼지 모이면 행성 되는 거 아님?",
                "author": "ㅇㅇ",
                "ip_hash": "1.2",
                "created_at": "2026-06-01 12:01:00",
            },
            {
                "post_no": "11",
                "title": "목성 고리",
                "content": "이건 좀 신기하네 ㅋㅋ",
                "author": "ㅇㅇ",
                "ip_hash": "1.2",
                "created_at": "2026-06-01 13:02:00",
            },
            {
                "post_no": "12",
                "title": "다른 사람",
                "content": "토성 사진 봤음",
                "author": "고닉",
                "user_id": "fixed-user",
                "created_at": "2026-06-01 13:05:00",
            },
        ],
        gallery_id="universe",
    )

    assert result["summary"]["actor_count"] == 2
    first = result["actors"][0]
    assert first["post_count"] == 2
    assert first["comment_count"] == 0
    assert "목성" in first["top_terms"]
    assert first["style"]["laugh_rate"] > 0
    assert first["style"]["question_rate"] > 0


def test_analyze_actors_uses_comment_identity_when_available() -> None:
    result = actor_analysis.analyze_actors(
        [
            {
                "post_no": "20",
                "title": "원글",
                "author": "작성자",
                "comments": [
                    {
                        "comment_id": "c1",
                        "author": "댓글러",
                        "ip_hint": "8.8",
                        "content": "그건 아닌 거 같은데?",
                        "created_at": "14:03:00",
                    },
                    "작성자 정보 없는 댓글",
                ],
            }
        ],
        gallery_id="boardgame",
    )

    assert result["summary"]["actor_count"] == 2
    assert result["summary"]["observed_comment_count"] == 1
    assert result["summary"]["skipped_comment_count"] == 1
    assert any(actor["comment_count"] == 1 for actor in result["actors"])


def test_actor_keys_do_not_expose_raw_identity() -> None:
    result = actor_analysis.analyze_actors(
        [
            {
                "post_no": "1",
                "title": "테스트",
                "author": "very-secret-nickname",
                "ip_hash": "123.45",
            }
        ],
        gallery_id="x",
    )

    actor = result["actors"][0]
    assert actor["actor_key"].startswith("actor:")
    assert "very-secret-nickname" not in actor["actor_key"]
    assert "123.45" not in actor["actor_key"]


def test_fixed_id_groups_even_when_display_name_changes() -> None:
    result = actor_analysis.analyze_actors(
        [
            {
                "post_no": "1",
                "title": "첫 글",
                "author": "old-name",
                "user_id": "stable-user",
            },
            {
                "post_no": "2",
                "title": "둘째 글",
                "author": "new-name",
                "user_id": "stable-user",
            },
        ],
        gallery_id="boardgame",
    )

    assert result["summary"]["actor_count"] == 1
    assert result["actors"][0]["post_count"] == 2
