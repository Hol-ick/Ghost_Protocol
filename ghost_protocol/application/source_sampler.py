"""Read-only multi-gallery sampling for prompt calibration.

This module intentionally does not call a remote LLM and does not mutate the active
briefing/draft state.  It collects compact source snapshots from one or more
gallery ids and formats them as a copy-friendly Markdown package.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Callable

from ghost_protocol.domain import board_rhythm


VALID_GALLERY_TYPES = {"board", "mgallery", "mini"}


TITLE_PATTERN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("비교/선택형", (" vs ", "VS", "비교", "골라", "추천", "뭐가", "어느")),
    ("후기/경험형", ("후기", "해봄", "봤다", "샀다", "먹어봄", "플레이함")),
    ("정보/정리형", ("정보", "정리", "팁", "공략", "공지", "요약")),
    ("첨부/짤 반응형", (".jpg", ".png", ".gif", ".webp", ".mp4", "짤", "사진", "영상")),
)


TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("보드게임/플레이", ("보드게임", "보드겜", "게임", "룰", "카드", "덱", "확장", "플레이", "전략", "파티")),
    ("우주/과학", ("우주", "행성", "은하", "별", "망원경", "천문", "NASA", "스페이스", "로켓", "위성")),
    ("스포츠/경기", ("야구", "축구", "경기", "선수", "감독", "리그", "타자", "투수", "득점")),
    ("게임/온라인", ("패치", "서버", "캐릭", "스킬", "직업", "퀘스트", "던전", "랭크")),
    ("만화/애니/웹툰", ("만화", "애니", "웹툰", "작가", "그림", "캐릭터", "번역", "연재")),
    ("정치/사회", ("선거", "정당", "정치", "시위", "정부", "대통령", "국회", "정책", "투표")),
    ("경제/생활비", ("주식", "코스피", "환율", "물가", "부동산", "금리", "월급", "소비", "대출")),
    ("연예/방송", ("아이돌", "배우", "연예인", "방송", "예능", "드라마", "유튜브", "라이브")),
    ("음식/생활", ("밥", "음식", "커피", "빵", "맛", "식당", "라면", "치킨", "여행")),
)


ROUGH_LANGUAGE_RE = re.compile(
    r"(시발|씨발|병신|새끼|좆|ㅈㄴ|존나|개같|꺼져|죽어|창녀|벌레|찐따)",
    re.IGNORECASE,
)


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


def format_gallery_spec_token(gallery_id: str, gallery_type: str = "mgallery") -> str:
    """Format a gallery spec for the sampler input box."""

    clean_id = re.sub(r"[^0-9A-Za-z_]", "", str(gallery_id or "").strip())
    clean_type = str(gallery_type or "").strip().lower()
    if clean_type not in VALID_GALLERY_TYPES:
        clean_type = "mgallery"
    if not clean_id:
        return ""
    return f"{clean_id}:{clean_type}"


def format_gallery_specs_input(specs: list[GallerySampleSpec]) -> str:
    """Return the canonical multi-line sampler input text."""

    return "\n".join(
        token
        for token in (format_gallery_spec_token(spec.gallery_id, spec.gallery_type) for spec in specs)
        if token
    )


def add_gallery_spec(
    raw: str,
    gallery_id: str,
    gallery_type: str = "mgallery",
    *,
    default_type: str = "mgallery",
) -> str:
    """Append a gallery spec to existing sampler text without duplicating it."""

    specs = parse_gallery_specs(raw, default_type=default_type)
    new_token = format_gallery_spec_token(gallery_id, gallery_type)
    if not new_token:
        return format_gallery_specs_input(specs)

    new_spec = parse_gallery_specs(new_token, default_type=default_type)
    if not new_spec:
        return format_gallery_specs_input(specs)
    candidate = new_spec[0]

    seen = {(spec.gallery_id, spec.gallery_type) for spec in specs}
    if (candidate.gallery_id, candidate.gallery_type) not in seen:
        specs.append(candidate)
    return format_gallery_specs_input(specs)


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
    comments_per_post = max(0, min(int(comments_per_post or 0), 3))
    detail_limit = (
        min(6, max(1, int(detail_limit_per_gallery)))
        if detail_limit_per_gallery is not None
        else min(pages * 2, 6)
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


def sample_quality_notes(bundle: dict) -> list[str]:
    """Return compact notes that make copied sample packages easier to review."""

    items = [item for item in list(bundle.get("items") or []) if isinstance(item, dict)]
    posts: list[dict] = []
    for item in items:
        result = item.get("result") or {}
        posts.extend(post for post in list(result.get("raw_posts") or []) if isinstance(post, dict))

    body_count = sum(1 for post in posts if str(post.get("content") or "").strip())
    comment_count = sum(len(list(post.get("comments") or [])) for post in posts)
    comments_per_post = int(bundle.get("comments_per_post") or 0)

    notes: list[str] = []
    if comments_per_post <= 0:
        notes.append("댓글 샘플 수집이 꺼져 있습니다. 댓글 작문까지 보정하려면 글당 2~3개 정도를 권장합니다.")
    elif comment_count <= 0 and posts:
        notes.append("댓글 수집 옵션은 켜져 있지만 수집된 댓글이 없습니다. 대상 게시판의 댓글 구조나 접근 제한을 확인해야 합니다.")
    if posts and body_count / max(len(posts), 1) < 0.35:
        notes.append("본문이 없는 글 비율이 높습니다. 제목 문체 분석에는 충분하지만 장문 본문 보정에는 약할 수 있습니다.")
    if len(items) >= 4 and int(bundle.get("pages") or 1) >= 4:
        notes.append("여러 게시판을 깊게 수집했습니다. 프롬프트 보정용으로는 게시판당 1~3페이지 샘플이 더 다루기 쉽습니다.")
    if not notes:
        notes.append("본문과 댓글 샘플이 함께 들어 있어 작문 프롬프트 보정에 사용할 수 있는 상태입니다.")
    return notes


def _ratio(count: int, total: int) -> float:
    return round(count / max(total, 1), 3)


def _counter_rows(counter: Counter[str], total: int, *, limit: int = 5) -> list[dict[str, Any]]:
    return [
        {"label": label, "count": count, "ratio": _ratio(count, total)}
        for label, count in counter.most_common(limit)
    ]


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def _classify_title_pattern(title: str) -> str:
    text = f" {str(title or '').strip()} "
    lowered = text.lower()
    if not text.strip():
        return "무제/빈 제목"
    for label, keywords in TITLE_PATTERN_RULES:
        if any(keyword.lower() in lowered for keyword in keywords):
            return label
    if "?" in text or _contains_any(text, ("뭐", "왜", "어케", "어떻게", "가능", "있나", "있음")):
        return "질문형"
    if len(text.strip()) <= 14:
        return "짧은 반응형"
    return "잡담/서술형"


def _classify_topic(text: str) -> str:
    haystack = str(text or "")
    for label, keywords in TOPIC_RULES:
        if _contains_any(haystack, keywords):
            return label
    if "?" in haystack or _contains_any(haystack, ("뭐", "왜", "어케", "어떻게", "추천", "가능")):
        return "질문/상담"
    if _contains_any(haystack, ("ㅋㅋ", "ㄷㄷ", "웃", "밈", "드립")):
        return "밈/가벼운 반응"
    return "일상/잡담"


def _classify_body_length(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return "본문 없음"
    line_count = len([line for line in text.splitlines() if line.strip()])
    if len(text) <= 30:
        return "한 줄/초단문"
    if len(text) <= 180 and line_count <= 3:
        return "1~3줄 단문"
    if len(text) <= 700:
        return "중간 길이"
    return "장문"


def _classify_comment_role(comment: str) -> str:
    text = _clean_line(comment, limit=160)
    if not text:
        return "빈 댓글"
    if "?" in text or _contains_any(text, ("뭐", "왜", "어케", "어떻게", "가능", "맞음")):
        return "확인/질문"
    if _contains_any(text, ("아님", "틀림", "그게 아니라", "정확히", "반대로")):
        return "정정/반박"
    if _contains_any(text, ("추천", "해봐", "ㄱㄱ", "괜찮", "무난")):
        return "추천/제안"
    if _contains_any(text, ("나도", "내가", "해봤", "먹어봤", "써봤", "갔다")):
        return "경험 추가"
    if _contains_any(text, ("근데", "아니", "별로", "오히려")):
        return "가벼운 반박"
    if len(text) <= 12 or re.fullmatch(r"[ㅋㅎㄷ\s\.\!\?]+", text):
        return "짧은 반응"
    return "정보/덧붙임"


def _safe_percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def _profile_guidance(profile: dict[str, Any]) -> str:
    topics = ", ".join(row["label"] for row in profile.get("topic_mix", [])[:3]) or "수집 소재"
    title_patterns = ", ".join(row["label"] for row in profile.get("title_patterns", [])[:3]) or "기존 제목 구조"
    body_mix = profile.get("body_length_mix", [])
    primary_body = body_mix[0]["label"] if body_mix else "수집된 본문 길이"
    comment_roles = ", ".join(row["label"] for row in profile.get("comment_roles", [])[:3])

    guidance = (
        f"주요 소재는 {topics} 정도로만 참고하고, 말투를 강하게 모방하지 않는다. "
        f"제목은 {title_patterns} 패턴을 섞고, 본문은 {primary_body} 비중을 우선 반영한다."
    )
    if comment_roles:
        guidance += f" 댓글은 {comment_roles} 역할을 섞어 공감만 반복하지 않게 한다."
    if profile.get("caution_notes"):
        guidance += " 경고 메모가 있는 소재는 직접 재현보다 구조적 특징만 가져온다."
    return guidance


def _profile_caution_notes(
    *,
    posts: list[dict],
    comments: list[str],
    body_counter: Counter[str],
    topic_counter: Counter[str],
) -> list[str]:
    notes: list[str] = []
    total_posts = len(posts)
    if not comments and total_posts:
        notes.append("댓글 샘플이 없어 댓글 작문 보정은 약합니다.")
    if body_counter.get("본문 없음", 0) / max(total_posts, 1) >= 0.55:
        notes.append("본문 없는 글이 많아 제목 구조 위주로만 반영하는 편이 안전합니다.")
    if topic_counter and topic_counter.most_common(1)[0][1] / max(total_posts, 1) >= 0.65:
        notes.append("한 소재 쏠림이 강합니다. 초안 생성 시 보조 소재 슬롯을 함께 열어 두는 편이 좋습니다.")
    rough_units = 0
    text_units = 0
    for post in posts:
        combined = f"{post.get('title') or ''} {post.get('source_title') or ''} {post.get('content') or ''}"
        if combined.strip():
            text_units += 1
            rough_units += 1 if ROUGH_LANGUAGE_RE.search(combined) else 0
    for comment in comments:
        if str(comment).strip():
            text_units += 1
            rough_units += 1 if ROUGH_LANGUAGE_RE.search(str(comment)) else 0
    if rough_units / max(text_units, 1) >= 0.2:
        notes.append("비속어/과격 표현 신호가 많습니다. 표현 자체보다 글 구조와 반응 역할만 참고합니다.")
    return notes


def analyze_sample_bundle(bundle: dict) -> dict[str, Any]:
    """Build a prompt-calibration profile from collected source samples.

    The profile is intentionally structural.  It summarizes topic mix, title
    shapes, body-length distribution, and comment roles without trying to clone
    a board's exact diction.
    """

    items = [item for item in list(bundle.get("items") or []) if isinstance(item, dict)]
    profiles: list[dict[str, Any]] = []
    overall_topics: Counter[str] = Counter()
    overall_titles: Counter[str] = Counter()
    overall_bodies: Counter[str] = Counter()
    overall_comments: Counter[str] = Counter()
    total_posts = 0
    total_comments = 0

    for item in items:
        result = item.get("result") or {}
        posts = [post for post in list(result.get("raw_posts") or []) if isinstance(post, dict)]
        title_counter: Counter[str] = Counter()
        topic_counter: Counter[str] = Counter()
        body_counter: Counter[str] = Counter()
        comment_counter: Counter[str] = Counter()
        comments: list[str] = []

        for post in posts:
            title = _post_title(post)
            content = str(post.get("content") or "")
            title_pattern = _classify_title_pattern(title)
            topic = _classify_topic(f"{title} {content}")
            body_length = _classify_body_length(content)

            title_counter[title_pattern] += 1
            topic_counter[topic] += 1
            body_counter[body_length] += 1

            for comment in list(post.get("comments") or []):
                clean_comment = _clean_line(comment, limit=220)
                if not clean_comment:
                    continue
                comments.append(clean_comment)
                comment_counter[_classify_comment_role(clean_comment)] += 1

        profile = {
            "gallery_id": str(item.get("gallery_id") or ""),
            "gallery_type": str(item.get("gallery_type") or ""),
            "post_count": len(posts),
            "body_count": sum(1 for post in posts if str(post.get("content") or "").strip()),
            "comment_count": len(comments),
            "topic_mix": _counter_rows(topic_counter, len(posts)),
            "title_patterns": _counter_rows(title_counter, len(posts)),
            "body_length_mix": _counter_rows(body_counter, len(posts)),
            "comment_roles": _counter_rows(comment_counter, len(comments)),
            "caution_notes": _profile_caution_notes(
                posts=posts,
                comments=comments,
                body_counter=body_counter,
                topic_counter=topic_counter,
            ),
        }
        profile["generation_guidance"] = _profile_guidance(profile)
        profiles.append(profile)

        overall_topics.update(topic_counter)
        overall_titles.update(title_counter)
        overall_bodies.update(body_counter)
        overall_comments.update(comment_counter)
        total_posts += len(posts)
        total_comments += len(comments)

    return {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_collected_at": bundle.get("collected_at") or "",
        "pages": int(bundle.get("pages") or 1),
        "comments_per_post": int(bundle.get("comments_per_post") or 0),
        "gallery_count": len(items),
        "post_count": total_posts,
        "comment_count": total_comments,
        "profiles": profiles,
        "overall": {
            "topic_mix": _counter_rows(overall_topics, total_posts),
            "title_patterns": _counter_rows(overall_titles, total_posts),
            "body_length_mix": _counter_rows(overall_bodies, total_posts),
            "comment_roles": _counter_rows(overall_comments, total_comments),
        },
        "sample_notes": sample_quality_notes(bundle),
    }


def _format_rows(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["- (샘플 없음)"]
    return [
        f"- {row.get('label')} · {row.get('count')}개 · {_safe_percent(float(row.get('ratio') or 0))}"
        for row in rows
    ]


def format_sample_analysis_markdown(analysis: dict) -> str:
    """Format a sample-analysis profile for copy/prompt review."""

    lines: list[str] = [
        "# 게시판 샘플 분석 프로필",
        "",
        f"- 분석 시각: {analysis.get('created_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 수집 시각: {analysis.get('source_collected_at') or ''}",
        f"- 게시판 수: {analysis.get('gallery_count', 0)}개",
        f"- 원본 글: {analysis.get('post_count', 0)}개",
        f"- 댓글 샘플: {analysis.get('comment_count', 0)}개",
        f"- 수집 범위: {analysis.get('pages', 1)}페이지 · 글당 댓글 {analysis.get('comments_per_post', 0)}개",
        "",
        "## 사용 원칙",
        "- 문체를 깊게 복제하지 않고 제목 구조, 본문 길이 분포, 댓글 역할, 주제 비율만 참고합니다.",
        "- 위험하거나 과격한 표현은 직접 재현하지 말고 소재 선택과 길이 조절 신호로만 사용합니다.",
    ]

    sample_notes = list(analysis.get("sample_notes") or [])
    if sample_notes:
        lines.extend(["", "## 샘플 메모"])
        lines.extend(f"- {note}" for note in sample_notes)

    overall = analysis.get("overall") or {}
    lines.extend(["", "## 전체 경향", "", "### 주제 분포"])
    lines.extend(_format_rows(list(overall.get("topic_mix") or [])))
    lines.extend(["", "### 제목 패턴"])
    lines.extend(_format_rows(list(overall.get("title_patterns") or [])))
    lines.extend(["", "### 본문 길이"])
    lines.extend(_format_rows(list(overall.get("body_length_mix") or [])))
    lines.extend(["", "### 댓글 역할"])
    lines.extend(_format_rows(list(overall.get("comment_roles") or [])))

    for profile in list(analysis.get("profiles") or []):
        gallery_id = profile.get("gallery_id") or "(unknown)"
        lines.extend(
            [
                "",
                f"## {gallery_id}",
                "",
                f"- 타입: `{profile.get('gallery_type') or ''}`",
                f"- 원본 글: {profile.get('post_count', 0)}개",
                f"- 본문 포함: {profile.get('body_count', 0)}개",
                f"- 댓글 샘플: {profile.get('comment_count', 0)}개",
                "",
                "### 주제 분포",
            ]
        )
        lines.extend(_format_rows(list(profile.get("topic_mix") or [])))
        lines.extend(["", "### 제목 패턴"])
        lines.extend(_format_rows(list(profile.get("title_patterns") or [])))
        lines.extend(["", "### 본문 길이"])
        lines.extend(_format_rows(list(profile.get("body_length_mix") or [])))
        lines.extend(["", "### 댓글 역할"])
        lines.extend(_format_rows(list(profile.get("comment_roles") or [])))

        caution_notes = list(profile.get("caution_notes") or [])
        if caution_notes:
            lines.extend(["", "### 주의 신호"])
            lines.extend(f"- {note}" for note in caution_notes)

        lines.extend(["", "### 작문 보정 가이드", "", str(profile.get("generation_guidance") or "")])

    return "\n".join(lines).strip()


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
    quality_notes = sample_quality_notes(bundle)
    if quality_notes:
        lines.extend(["", "## 샘플 품질 메모"])
        lines.extend(f"- {note}" for note in quality_notes)

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
