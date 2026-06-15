"""Finite rehearsal-cycle helpers.

Rehearsal intentionally never publishes. Each cycle analyzes the drafts from
the previous cycle while keeping a compact source-board anchor, so the loop can
improve style without drifting into topics that were never present upstream.
"""

from __future__ import annotations

import datetime
import re
from collections import Counter
from typing import Any

from ghost_protocol import content_filter
from ghost_protocol.domain import gallery_purpose
from ghost_protocol.domain import rehearsal_policy


DEFAULT_CYCLE_LIMIT = 3
MIN_CYCLE_LIMIT = 1
MAX_CYCLE_LIMIT = 20
ANCHOR_POST_LIMIT = 24
ANCHOR_COMMENT_LIMIT = 2
LOW_SUCCESS_MIN_VALID = 5

_TERM_STOPWORDS = {
    "이거",
    "그거",
    "저거",
    "좀",
    "진짜",
    "그냥",
    "너무",
    "아님",
    "같음",
    "듯",
    "왜",
    "자꾸",
    "계속",
    "이번",
    "저런",
    "이런",
    "그런",
}


def normalize_cycle_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_CYCLE_LIMIT
    return max(MIN_CYCLE_LIMIT, min(MAX_CYCLE_LIMIT, parsed))


def _post_title(post: dict) -> str:
    return str(post.get("title") or post.get("source_title") or "").strip()


def _post_content(post: dict) -> str:
    return str(post.get("content") or post.get("body") or "").strip()


def _comment_texts(post: dict, *, limit: int = ANCHOR_COMMENT_LIMIT) -> list[str]:
    values = post.get("comments") or post.get("target_comments") or []
    comments: list[str] = []
    for value in values:
        if isinstance(value, dict):
            text = str(value.get("comment") or value.get("content") or "").strip()
        else:
            text = str(value or "").strip()
        if not text or content_filter.classify_noise_text(text).is_noise:
            continue
        comments.append(text)
        if len(comments) >= limit:
            break
    return comments


def _clean_anchor_posts(posts: Any, *, limit: int = ANCHOR_POST_LIMIT) -> list[dict]:
    """Return source posts safe enough to keep as a rehearsal drift anchor."""

    cleaned: list[dict] = []
    seen: set[str] = set()
    for post in posts or ():
        if not isinstance(post, dict):
            continue
        title = _post_title(post)
        content = _post_content(post)
        if not title:
            continue
        source_text = f"{title}\n{content}"
        if content_filter.classify_noise_text(source_text).is_noise:
            continue
        key = f"{post.get('post_no') or ''}|{title}".casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(
            {
                "post_no": str(post.get("post_no") or "").strip(),
                "title": title,
                "content": content,
                "comments": _comment_texts(post),
            }
        )
        if len(cleaned) >= limit:
            break
    return cleaned


def build_analysis_payload(
    scripts: list[dict],
    *,
    gallery_id: str,
    anchor_posts: Any = (),
    anchor_topic: str = "",
) -> dict:
    """Build the same lightweight shape used by ``GhostBrain.analyze_trend``."""

    valid = [item for item in scripts if not item.get("_failed")]
    failed = [item for item in scripts if item.get("_failed")]
    anchors = _clean_anchor_posts(anchor_posts)
    low_success = len(valid) < LOW_SUCCESS_MIN_VALID
    titles = [
        str(item.get("title") or "").strip()
        for item in valid
        if str(item.get("title") or "").strip()
    ]
    comments: list[str] = []
    raw_posts: list[dict] = []

    for index, item in enumerate(valid, start=1):
        content = str(item.get("content") or "").strip()
        target_comments = list(item.get("target_comments") or [])
        comment_texts = [
            str(comment.get("comment") or "").strip()
            for comment in target_comments
            if str(comment.get("comment") or "").strip()
        ]
        comments.extend(comment_texts)
        raw_posts.append(
            {
                "post_no": f"rehearsal-{index}",
                "title": str(item.get("title") or "").strip(),
                "content": content,
                "comments": comment_texts,
            }
        )

    anchor_slice = anchors if low_success else anchors[:8]
    for index, post in enumerate(anchor_slice, start=1):
        titles.append(post["title"])
        comments.extend(post["comments"])
        raw_posts.append(
            {
                "post_no": post.get("post_no") or f"source-anchor-{index}",
                "title": post["title"],
                "content": post["content"],
                "comments": post["comments"],
                "source": "original_board_anchor",
            }
        )

    return {
        "gallery_id": gallery_id,
        "titles": titles,
        "comments": comments,
        "authors": [],
        "raw_posts": raw_posts,
        "total_post_count": len(raw_posts),
        "ai_post_count": len(valid),
        "rehearsal_valid_count": len(valid),
        "rehearsal_anchor_count": len(anchor_slice),
        "rehearsal_anchor_topic": str(anchor_topic or "").strip(),
        "rehearsal_failure_patterns": [
            rehearsal_policy.failure_pattern_label(item.get("_failure_reason"))
            for item in failed
        ],
    }


def _repeated_terms(scripts: list[dict], *, limit: int = 8) -> list[str]:
    counter: Counter[str] = Counter()
    for item in scripts:
        if item.get("_failed"):
            continue
        text = f"{item.get('title') or ''} {item.get('content') or ''}"
        for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", text):
            lowered = token.casefold()
            if lowered in _TERM_STOPWORDS:
                continue
            counter[token] += 1
    return [term for term, count in counter.most_common(limit) if count >= 2]


def _successful_titles(scripts: list[dict], *, limit: int = 8) -> list[str]:
    return [
        str(item.get("title") or "").strip()
        for item in scripts
        if not item.get("_failed") and str(item.get("title") or "").strip()
    ][:limit]


def _failure_patterns(scripts: list[dict], *, limit: int = 5) -> list[str]:
    counter: Counter[str] = Counter()
    for item in scripts:
        if not item.get("_failed"):
            continue
        counter[rehearsal_policy.failure_pattern_label(item.get("_failure_reason"))] += 1
    return [f"{label} {count}회" for label, count in counter.most_common(limit)]


def _clean_rehearsal_text(text: Any, *, gallery_id: str = "") -> str:
    cleaned = gallery_purpose.strip_identity_echo(str(text or "").strip(), gallery_id)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"(현재\s*수집분(?:에)?서는\s*){2,}", "현재 수집분에서는 ", cleaned).strip()
    return cleaned


def _success_stats(scripts: list[dict]) -> tuple[int, int, float]:
    total = max(10, len(scripts))
    valid = sum(1 for item in scripts if not item.get("_failed"))
    ratio = valid / total if total else 0.0
    return valid, total, ratio


def build_next_topic(
    intel: dict,
    scripts: list[dict],
    *,
    gallery_id: str = "",
    anchor_posts: Any = (),
    anchor_topic: str = "",
) -> str:
    """Turn rehearsal analysis into the next cycle's complete writing context."""

    analysis = _clean_rehearsal_text(intel.get("ai_analysis"), gallery_id=gallery_id)
    guidance = _clean_rehearsal_text(intel.get("generation_guidance"), gallery_id=gallery_id)
    seed_summary = str(intel.get("summary") or "").strip()
    hot_topics = [
        str(item).strip()
        for item in (intel.get("hot_topics") or [])
        if str(item).strip()
    ]

    if not analysis:
        titles = _successful_titles(scripts, limit=5)
        analysis = "직전 리허설 원고에서 이어갈 소재: " + " / ".join(titles[:5])

    repeated = _repeated_terms(scripts)
    failure_patterns = _failure_patterns(scripts)
    sample_titles = _successful_titles(scripts)
    valid_count, total_count, success_ratio = _success_stats(scripts)
    anchors = _clean_anchor_posts(anchor_posts, limit=12)
    parts: list[str] = []
    if gallery_purpose.get_profile(gallery_id):
        parts.extend([gallery_purpose.rehearsal_context(gallery_id), ""])
    if anchor_topic:
        parts.extend(
            [
                "[원본 게시판 브리핑 앵커]",
                _clean_rehearsal_text(anchor_topic, gallery_id=gallery_id)[:1200],
                "",
            ]
        )
    if anchors:
        anchor_titles = " / ".join(post["title"] for post in anchors[:10])
        parts.extend(
            [
                "[원본 게시글 스냅샷 앵커]",
                "리허설 원고가 적거나 반복될 때는 아래 실제 수집글의 흐름을 우선한다.",
                anchor_titles,
                "",
            ]
        )
    parts.extend(["[리허설 직전 사이클 분석]", analysis])
    if hot_topics:
        parts.extend(["", "[주요 소재]", " / ".join(hot_topics[:4])])
    if seed_summary:
        parts.extend(["", "[씨앗 떡밥]", seed_summary])
    if guidance:
        parts.extend(["", "[작문 지시]", guidance])
        parts.extend(
            [
                "",
                "[작문 지시 보정]",
                "위 작문 지시에 뜻·유래·사용 맥락·진위 확인을 질문 형태로 다루라는 문장이 있더라도 그대로 따르지 않는다.",
                "`무슨 뜻/언제부터/진짜냐/사용 맥락` 질문은 실패율을 높이므로, 원본 안의 음식·시간·숫자·장면·댓글 반응 하나로 낮춰 평서형 반응을 만든다.",
                "확인 질문이 꼭 필요하면 배치 전체에서 1개만 쓰고, 나머지는 장면 관찰·가벼운 농담·생활 연결로 분산한다.",
            ]
        )
    if sample_titles:
        parts.extend(["", "[직전 성공 제목 샘플]", " / ".join(sample_titles)])
    if repeated:
        parts.extend(
            [
                "",
                "[직전 반복 명사]",
                " / ".join(repeated),
                "위 명사는 다음 사이클 제목에서 각각 0~1회만 사용한다. 같은 명사를 반복해야 한다면 원고를 실패 처리하고 다른 슬롯의 장면·수치·결과로 이동한다.",
            ]
        )
    if failure_patterns:
        parts.extend(
            [
                "",
                "[직전 실패 패턴]",
                " / ".join(failure_patterns),
                "실패 후보의 문구를 살리지 말고, 실패한 구조만 피한다.",
                "slot_drift는 소재가 완전히 틀렸다는 뜻이 아니라 배합이 뻣뻣했다는 신호다. 다음 사이클에서는 원본 앵커의 다른 장면을 더 많이 쓴다.",
                "duplicate_loop나 meta_reaction이 많으면 같은 명사 질문을 중단하고, 작은 사물·시간·숫자·이미지 장면으로 바꾼다.",
            ]
        )
    if success_ratio < 0.6:
        parts.extend(
            [
                "",
                "[저성공률 복구 규칙]",
                f"직전 사이클 성공이 {valid_count}/{total_count}개뿐이므로 성공 원고만으로 유행을 확정하지 않는다.",
                "성공 원고가 5개 미만이면 생성 원고보다 원본 게시글 스냅샷 앵커를 먼저 신뢰한다.",
                "다음 사이클은 직전 성공 제목을 말바꾸기하지 말고 [R]/[G]/서브 슬롯을 먼저 써서 소재 폭을 회복한다.",
                "실패가 반복된 민감 소재는 반박문으로 살리지 말고 안전한 원본 장면 또는 상시 분야 장면으로 대체한다.",
                "정상적인 원본 소재를 '금지 화제'처럼 버리지 말고 소프트 쿨다운으로 다룬다. 같은 제목 구조만 피한다.",
            ]
        )
    parts.extend(
        [
            "",
            "[다음 사이클 소재 배합]",
            "- 10개 기준: 직전 핵심 소재 최대 2~3개, 옆 소재/댓글 파생 3개, 상시 분야 소재 1~2개, 가벼운 생활·숫자·장면 2개.",
            "- 직전 사이클에서 한 소재가 과점했으면 같은 소재의 질문·불평·지적 글을 중단하고, 다른 슬롯의 독립 장면으로 흘린다.",
            "- 주제 전환은 '왜 이 얘기함'이 아니라 새 구체 소재를 조용히 시작하는 방식으로 한다.",
            "- 제목이 질문형이면 배치 전체에서 최대 1개만 허용한다. 나머지는 평서형 장면 반응으로 쓴다.",
            "- 불평/지적/교정은 배치의 중심이 아니다. 가능한 경우 관찰, 추가 정보, 농담, 개인 스케일, 다음 장면 예상으로 바꾼다.",
            "- 이전 성공 제목의 핵심 명사를 다시 쓰려면 본문에 새 정보 하나를 반드시 더한다. 새 정보가 없으면 다른 앵커 글로 이동한다.",
            "",
            "[리허설 전용 규칙]",
            "이 입력은 직전 리허설 원고와 최초 원본 게시글 앵커를 함께 분석한 결과다.",
            "직전 문장을 바꿔 쓰지 말고, 남은 구체 장면과 자연스러운 후속 반응으로 전개한다.",
            "직전 사이클의 유행 소재가 게시판의 지속 기본축을 덮어쓰지 않게 한다.",
            "생성 원고와 원본 스냅샷이 충돌하면 원본 스냅샷을 우선한다.",
            "상시 분야 슬롯은 갤러리 이름을 말하지 않고 해당 분야의 구체 장면으로 바로 시작한다.",
            "다음 사이클 분석 문장에는 갤러리 ID/기본 분야 설명을 반복하지 않는다. 현재 보이는 흐름과 다음 배합만 말한다.",
        ]
    )
    return "\n".join(parts).strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _clean_intel_text(text: str, *, gallery_id: str = "") -> str:
    return _clean_rehearsal_text(text, gallery_id=gallery_id)


def _intel_analysis(intel: dict, *, gallery_id: str = "") -> str:
    return _clean_intel_text(
        _first_text(
            intel.get("ai_analysis"),
            intel.get("summary"),
            "분석 없음",
        ),
        gallery_id=gallery_id,
    )


def _intel_guidance(intel: dict, *, gallery_id: str = "") -> str:
    guidance = _clean_intel_text(intel.get("generation_guidance"), gallery_id=gallery_id)
    if guidance:
        return guidance
    hot_topics = [
        str(item).strip()
        for item in (intel.get("hot_topics") or [])
        if str(item).strip()
    ]
    if hot_topics:
        return "다음 사이클은 " + " / ".join(hot_topics[:4]) + " 소재를 분산한다."
    return "다음 사이클 작문 지시 없음"


def _shorten_line(text: Any, *, limit: int = 120) -> str:
    one_line = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(one_line) <= limit:
        return one_line
    return one_line[: max(0, limit - 1)].rstrip() + "…"


def _script_by_wave(scripts: list[dict]) -> dict[int, dict]:
    by_wave: dict[int, dict] = {}
    for fallback_index, item in enumerate(scripts, start=1):
        try:
            wave = int(item.get("wave") or fallback_index)
        except (TypeError, ValueError):
            wave = fallback_index
        by_wave[wave] = item
    return by_wave


def _expected_count(run: dict, scripts: list[dict]) -> int:
    raw = run.get("expected_count") or run.get("wave_count")
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = 0
    if parsed > 0:
        return parsed
    max_wave = 0
    for fallback_index, item in enumerate(scripts, start=1):
        try:
            max_wave = max(max_wave, int(item.get("wave") or fallback_index))
        except (TypeError, ValueError):
            max_wave = max(max_wave, fallback_index)
    return max(10, max_wave)


def _format_comment_lines(item: dict) -> list[str]:
    target_comments = list(item.get("target_comments") or [])
    if not target_comments:
        return []
    lines = ["   - 댓글:"]
    for comment in target_comments:
        post_no = str(comment.get("post_no") or "").strip()
        comment_text = _shorten_line(comment.get("comment"), limit=160)
        prefix = f"#{post_no}: " if post_no else ""
        lines.append(f"     - {prefix}{comment_text}")
    return lines


def format_markdown(runs: list[dict], *, gallery_id: str = "") -> str:
    created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cycle_total = len(runs)
    planned_total = cycle_total
    for run in runs:
        try:
            planned_total = max(planned_total, int(run.get("cycle_limit") or 0))
        except (TypeError, ValueError):
            pass
    lines = [
        "# 리허설 결과",
        "",
        f"- 복사 시각: {created_at}",
        f"- 게시판: `{gallery_id}`" if gallery_id else "- 게시판: 미지정",
        f"- 완료 사이클: {cycle_total}개",
    ]

    for run in runs:
        cycle = int(run.get("cycle") or 0)
        scripts = list(run.get("scripts") or [])
        valid = [item for item in scripts if not item.get("_failed")]
        failed = [item for item in scripts if item.get("_failed")]
        intel = dict(run.get("intel") or {})
        expected_count = _expected_count(run, scripts)
        by_wave = _script_by_wave(scripts)
        cycle_log = list(run.get("log_lines") or [])
        lines.extend(
            [
                "",
                f"## 사이클 {cycle} / {planned_total}",
                "",
                f"- 현재 사이클: {cycle}/{planned_total}",
                f"- 생성 성공: {len(valid)}개",
                f"- 생성 실패: {len(failed)}개",
            ]
        )

        lines.extend(["", "### 사이클 로그", ""])
        if cycle_log:
            lines.extend(f"- {str(entry).strip()}" for entry in cycle_log if str(entry).strip())
        else:
            lines.extend(
                [
                    f"- [REHEARSAL] 사이클 {cycle}/{planned_total} 원고 생성 완료",
                    f"- [REHEARSAL] 사이클 {cycle}/{planned_total} 주제와 작문 지시 재분석 완료",
                ]
            )

        lines.extend(
            [
                "",
                "### 다음 사이클 주제",
                "",
                _intel_analysis(intel, gallery_id=gallery_id),
                "",
                "### 다음 사이클 작문 지시",
                "",
                _intel_guidance(intel, gallery_id=gallery_id),
            ]
        )

        repeated = _repeated_terms(scripts, limit=6)
        if repeated:
            lines.extend(["", "### 반복 경향", "", "- " + " / ".join(repeated)])

        lines.extend(["", f"### 원고 {expected_count}개 목록", ""])
        for wave in range(1, expected_count + 1):
            item = by_wave.get(wave)
            if not item:
                lines.append(f"{wave}. [누락] 원고 데이터 없음")
                continue
            persona = str(item.get("persona_name") or item.get("persona") or "미지정")
            if item.get("_failed"):
                failure_title = _first_text(
                    item.get("title"),
                    item.get("_candidate_title"),
                    "복구 가능한 제목 없음",
                )
                failure_content = _first_text(
                    item.get("content"),
                    item.get("_candidate_content"),
                    "복구 가능한 본문 없음",
                )
                lines.extend(
                    [
                        f"{wave}. [실패] {persona} — {failure_title}",
                        f"   - 후보 본문: {_shorten_line(failure_content, limit=180)}",
                        f"   - 사유: {_shorten_line(item.get('_failure_reason') or '검증 실패', limit=220)}",
                    ]
                )
                lines.extend(_format_comment_lines(item))
                continue
            lines.extend(
                [
                    f"{wave}. [성공] {persona} — {str(item.get('title') or '').strip()}",
                    f"   - 본문: {_shorten_line(item.get('content'), limit=180)}",
                ]
            )
            lines.extend(_format_comment_lines(item))

    return "\n".join(lines).strip() + "\n"
