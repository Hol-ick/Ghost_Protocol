"""Read-only multi-gallery sampling for prompt calibration.

This module intentionally does not call Gemini and does not mutate the active
briefing/draft state.  It collects compact source snapshots from one or more
gallery ids and formats them as a copy-friendly Markdown package.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Callable

from ghost_protocol.domain import board_rhythm


VALID_GALLERY_TYPES = {"board", "mgallery", "mini"}


@dataclass(frozen=True)
class GallerySampleSpec:
    gallery_id: str
    gallery_type: str = "mgallery"


def parse_gallery_specs(
    raw: str,
    *,
    default_type: str = "mgallery",
) -> list[GallerySampleSpec]:
    """Parse newline/comma/space-separated gallery ids.

    Supported forms:
    - ``universe``
    - ``boardgame:mgallery``
    - ``baseball_new13|board``
    """

    fallback_type = default_type if default_type in VALID_GALLERY_TYPES else "mgallery"
    specs: list[GallerySampleSpec] = []
    seen: set[tuple[str, str]] = set()

    for chunk in re.split(r"[\s,]+", str(raw or "")):
        token = chunk.strip()
        if not token:
            continue

        gallery_id = token
        gallery_type = fallback_type
        for sep in ("|", ":"):
            if sep in token:
                left, right = token.split(sep, 1)
                gallery_id = left.strip()
                maybe_type = right.strip().lower()
                if maybe_type in VALID_GALLERY_TYPES:
                    gallery_type = maybe_type
                break

        gallery_id = re.sub(r"[^0-9A-Za-z_]", "", gallery_id)
        if not gallery_id:
            continue
        key = (gallery_id, gallery_type)
        if key in seen:
            continue
        seen.add(key)
        specs.append(GallerySampleSpec(gallery_id=gallery_id, gallery_type=gallery_type))

    return specs


def _clean_line(value: Any, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _escape_fence(text: str) -> str:
    return str(text or "").replace("```", "`\u200b``")


def collect_samples(
    specs: list[GallerySampleSpec],
    *,
    pages: int = 1,
    comments_per_post: int = 3,
    detail_limit_per_gallery: int | None = None,
    scraper_factory: Callable[[], Any] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict:
    """Collect read-only source samples for multiple galleries."""

    if scraper_factory is None:
        from ghost_protocol.scraper import TrendScraper

        scraper_factory = TrendScraper

    pages = max(1, min(int(pages or 1), 5))
    comments_per_post = max(0, min(int(comments_per_post or 0), 10))
    detail_limit = (
        max(1, int(detail_limit_per_gallery))
        if detail_limit_per_gallery is not None
        else min(pages * 30, 150)
    )

    bundle = {
        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pages": pages,
        "comments_per_post": comments_per_post,
        "items": [],
    }

    def log(message: str) -> None:
        if progress_callback:
            progress_callback(message)

    for index, spec in enumerate(specs, 1):
        item_logs: list[str] = []

        def item_log(message: str) -> None:
            item_logs.append(message)
            log(f"[{index}/{len(specs)}] {spec.gallery_id} · {message}")

        item: dict[str, Any] = {
            "gallery_id": spec.gallery_id,
            "gallery_type": spec.gallery_type,
            "logs": item_logs,
            "ok": False,
            "error": "",
            "result": {},
        }
        try:
            item_log(f"샘플 수집 시작 — {spec.gallery_type}, {pages}페이지")
            scraper = scraper_factory()
            result = scraper.collect_trending(
                gallery_id=spec.gallery_id,
                gallery_type=spec.gallery_type,
                pages=pages,
                source_detail_limit=detail_limit,
                source_comments_per_post=comments_per_post,
                progress_callback=item_log,
            )
            item["result"] = result
            item["ok"] = bool(result.get("raw_posts") or result.get("titles"))
            raw_count = len(list(result.get("raw_posts") or []))
            body_count = sum(
                1 for post in list(result.get("raw_posts") or []) if str(post.get("content") or "").strip()
            )
            comment_count = sum(len(list(post.get("comments") or [])) for post in list(result.get("raw_posts") or []))
            item_log(f"샘플 수집 완료 — 원본 {raw_count}개 / 본문 {body_count}개 / 댓글 {comment_count}개")
        except Exception as exc:  # noqa: BLE001 - keep sampling robust across mixed gallery ids
            item["error"] = str(exc)[:300]
            item_log(f"샘플 수집 실패 — {item['error']}")
        bundle["items"].append(item)

    return bundle


def _post_title(post: dict) -> str:
    return _clean_line(post.get("source_title") or post.get("title") or "(제목 없음)", limit=180)


def _post_content(post: dict, *, limit: int = 700) -> str:
    content = str(post.get("content") or "").strip()
    if not content:
        return "(본문 없음 또는 미수집)"
    if len(content) > limit:
        return content[: limit - 1].rstrip() + "…"
    return content


def _post_comments(post: dict, *, limit: int = 5) -> list[str]:
    comments: list[str] = []
    for comment in list(post.get("comments") or [])[:limit]:
        text = _clean_line(comment, limit=240)
        if text:
            comments.append(text)
    return comments


def format_sample_markdown(bundle: dict, *, max_posts_per_gallery: int = 90) -> str:
    """Format a multi-gallery sample bundle for one-click copy."""

    items = list(bundle.get("items") or [])
    lines: list[str] = [
        "# 게시판 샘플링 패키지",
        "",
        f"- 복사 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 수집 시각: {bundle.get('collected_at') or ''}",
        f"- 게시판 수: {len(items)}개",
        f"- 수집 페이지: {bundle.get('pages', 1)}페이지",
        f"- 댓글 샘플: 글당 최대 {bundle.get('comments_per_post', 0)}개",
        "",
        "이 패키지는 작문 프롬프트를 보정하기 위한 원본 제목/본문/댓글 샘플입니다.",
    ]

    for item in items:
        gallery_id = str(item.get("gallery_id") or "")
        gallery_type = str(item.get("gallery_type") or "")
        result = item.get("result") or {}
        posts = [post for post in list(result.get("raw_posts") or []) if isinstance(post, dict)]
        visible = posts[:max_posts_per_gallery]
        body_count = sum(1 for post in visible if str(post.get("content") or "").strip())
        comment_count = sum(len(list(post.get("comments") or [])) for post in visible)
        rhythm = board_rhythm.analyze_posting_rhythm(visible)

        lines.extend(
            [
                "",
                f"## {gallery_id}",
                "",
                f"- 타입: `{gallery_type}`",
                f"- 상태: {'성공' if item.get('ok') else '실패'}",
                f"- 원본 글: {len(visible)}개",
                f"- 본문 포함: {body_count}개",
                f"- 댓글 포함: {comment_count}개",
            ]
        )
        if item.get("error"):
            lines.append(f"- 오류: {item.get('error')}")
        if rhythm.get("interval_count"):
            lines.extend(
                [
                    f"- 글 간격 평균: {board_rhythm.format_seconds(rhythm.get('average_seconds'))}",
                    f"- 글 간격 중앙값: {board_rhythm.format_seconds(rhythm.get('median_seconds'))}",
                    f"- 추천 발행 간격: {rhythm.get('recommended_minutes')}분",
                ]
            )

        logs = [_clean_line(line, limit=240) for line in list(item.get("logs") or [])[-40:]]
        if logs:
            lines.extend(["", "### 수집 로그", "", "```text"])
            lines.extend(logs)
            lines.append("```")

        if not visible:
            lines.extend(["", "### 원본 글", "", "(수집된 원본 글이 없습니다.)"])
            continue

        lines.extend(["", "### 제목 목록"])
        for idx, post in enumerate(visible, 1):
            page = post.get("page")
            post_no = post.get("post_no") or post.get("no") or "?"
            created_at = _clean_line(post.get("created_at") or "", limit=40)
            meta = f"p{page} #{post_no}" if page else f"#{post_no}"
            if created_at:
                meta = f"{meta} · {created_at}"
            lines.append(f"{idx}. [{meta}] {_post_title(post)}")

        lines.extend(["", "### 제목 + 본문 + 댓글 세트"])
        for idx, post in enumerate(visible, 1):
            page = post.get("page")
            post_no = post.get("post_no") or post.get("no") or "?"
            created_at = _clean_line(post.get("created_at") or "", limit=40)
            comments = _post_comments(post)
            lines.extend(
                [
                    "",
                    f"#### {idx}. {_post_title(post)}",
                    f"- 위치: p{page} · #{post_no}" if page else f"- 위치: #{post_no}",
                    f"- 작성 시각: {created_at or '미수집'}",
                    f"- 댓글 수집: {len(comments)}개",
                    "",
                    "```text",
                    _escape_fence(_post_content(post)),
                    "```",
                ]
            )
            if comments:
                lines.extend(["", "댓글:"])
                for cidx, comment in enumerate(comments, 1):
                    lines.extend(
                        [
                            f"- 댓글 {cidx}",
                            "  ```text",
                            f"  {_escape_fence(comment)}",
                            "  ```",
                        ]
                    )
            else:
                lines.extend(["", "댓글: (없음 또는 미수집)"])

    return "\n".join(lines).strip()
