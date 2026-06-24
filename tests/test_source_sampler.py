from __future__ import annotations

from ghost_protocol.application import source_sampler


def test_parse_gallery_specs_accepts_multiple_forms() -> None:
    specs = source_sampler.parse_gallery_specs(
        "universe, boardgame:mgallery baseball_new13|board universe",
        default_type="mini",
    )

    assert [spec.gallery_id for spec in specs] == [
        "universe",
        "boardgame",
        "baseball_new13",
    ]
    assert [spec.gallery_type for spec in specs] == [
        "mini",
        "mgallery",
        "board",
    ]


def test_collect_samples_uses_each_gallery_spec() -> None:
    calls: list[tuple[str, str, int, int, int]] = []

    class FakeScraper:
        def collect_trending(
            self,
            *,
            gallery_id,
            gallery_type,
            pages,
            source_detail_limit,
            source_comments_per_post,
            progress_callback,
        ):
            calls.append(
                (
                    gallery_id,
                    gallery_type,
                    pages,
                    source_detail_limit,
                    source_comments_per_post,
                )
            )
            progress_callback("fake page done")
            return {
                "titles": [f"{gallery_id} title"],
                "raw_posts": [
                    {
                        "post_no": "10",
                        "page": 1,
                        "title": f"{gallery_id} title",
                        "content": "본문 샘플",
                        "comments": ["댓글 샘플"],
                        "created_at": "12:00",
                    }
                ],
            }

    specs = [
        source_sampler.GallerySampleSpec("universe", "mgallery"),
        source_sampler.GallerySampleSpec("boardgame", "board"),
    ]

    bundle = source_sampler.collect_samples(
        specs,
        pages=2,
        comments_per_post=4,
        scraper_factory=FakeScraper,
    )

    assert calls == [
        ("universe", "mgallery", 2, 60, 4),
        ("boardgame", "board", 2, 60, 4),
    ]
    assert [item["ok"] for item in bundle["items"]] == [True, True]
    assert "fake page done" in bundle["items"][0]["logs"]


def test_format_sample_markdown_includes_titles_bodies_and_comments() -> None:
    bundle = {
        "collected_at": "2026-06-24 21:00:00",
        "pages": 1,
        "comments_per_post": 2,
        "items": [
            {
                "gallery_id": "boardgame",
                "gallery_type": "mgallery",
                "ok": True,
                "logs": ["샘플 수집 완료"],
                "result": {
                    "raw_posts": [
                        {
                            "post_no": "123",
                            "page": 1,
                            "title": "보드게임 추천 좀",
                            "content": "둘이 할만한 게임 찾는 중",
                            "comments": ["아줄 무난함"],
                            "created_at": "14:20",
                        }
                    ]
                },
            }
        ],
    }

    text = source_sampler.format_sample_markdown(bundle)

    assert "# 게시판 샘플링 패키지" in text
    assert "## boardgame" in text
    assert "보드게임 추천 좀" in text
    assert "둘이 할만한 게임 찾는 중" in text
    assert "아줄 무난함" in text
