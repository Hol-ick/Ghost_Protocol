from __future__ import annotations

from ghost_protocol.application import source_sampler


def test_analyze_sample_bundle_extracts_structural_profile() -> None:
    bundle = {
        "collected_at": "2026-06-25 10:00:00",
        "pages": 1,
        "comments_per_post": 2,
        "items": [
            {
                "gallery_id": "boardgame",
                "gallery_type": "mgallery",
                "ok": True,
                "result": {
                    "raw_posts": [
                        {
                            "title": "아줄 vs 카탄 뭐가 나음?",
                            "content": "둘이 할만한 보드게임 찾는 중",
                            "comments": ["아줄 무난함", "카탄은 3명부터가 나음"],
                        },
                        {
                            "title": "카드게임 후기",
                            "content": "룰은 쉬운데 생각보다 오래 걸림",
                            "comments": ["나도 해봤는데 4인 재밌더라"],
                        },
                    ]
                },
            }
        ],
    }

    analysis = source_sampler.analyze_sample_bundle(bundle)

    assert analysis["gallery_count"] == 1
    assert analysis["post_count"] == 2
    profile = analysis["profiles"][0]
    assert profile["gallery_id"] == "boardgame"
    assert profile["topic_mix"][0]["label"] == "보드게임/플레이"
    assert {row["label"] for row in profile["title_patterns"]} >= {"비교/선택형", "후기/경험형"}
    assert any(row["label"] == "추천/제안" for row in profile["comment_roles"])
    assert "말투를 강하게 모방하지 않는다" in profile["generation_guidance"]


def test_format_sample_analysis_markdown_is_copy_ready() -> None:
    analysis = {
        "created_at": "2026-06-25 10:01:00",
        "source_collected_at": "2026-06-25 10:00:00",
        "gallery_count": 1,
        "post_count": 1,
        "comment_count": 1,
        "pages": 1,
        "comments_per_post": 1,
        "sample_notes": ["본문과 댓글 샘플이 함께 들어 있습니다."],
        "overall": {
            "topic_mix": [{"label": "질문/상담", "count": 1, "ratio": 1.0}],
            "title_patterns": [{"label": "질문형", "count": 1, "ratio": 1.0}],
            "body_length_mix": [{"label": "1~3줄 단문", "count": 1, "ratio": 1.0}],
            "comment_roles": [{"label": "정정/반박", "count": 1, "ratio": 1.0}],
        },
        "profiles": [
            {
                "gallery_id": "universe",
                "gallery_type": "mgallery",
                "post_count": 1,
                "body_count": 1,
                "comment_count": 1,
                "topic_mix": [{"label": "우주/과학", "count": 1, "ratio": 1.0}],
                "title_patterns": [{"label": "질문형", "count": 1, "ratio": 1.0}],
                "body_length_mix": [{"label": "1~3줄 단문", "count": 1, "ratio": 1.0}],
                "comment_roles": [{"label": "확인/질문", "count": 1, "ratio": 1.0}],
                "caution_notes": [],
                "generation_guidance": "제목 구조와 길이 분포만 반영한다.",
            }
        ],
    }

    text = source_sampler.format_sample_analysis_markdown(analysis)

    assert "# 게시판 샘플 분석 프로필" in text
    assert "## universe" in text
    assert "우주/과학 · 1개 · 100%" in text
    assert "제목 구조와 길이 분포만 반영한다." in text
