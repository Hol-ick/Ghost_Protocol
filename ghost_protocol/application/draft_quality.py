"""Fail-closed quality review for local draft candidates.

The writer remains probabilistic.  This module is the deterministic seam that
decides whether a candidate is safe to send to a local critic, repair, or the
posting workflow.  It deliberately reports stable issue codes instead of
trying to rewrite prose itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ghost_protocol.domain import naturalness

from .draft_pipeline import DraftCard, validate_draft


_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
_NUMBER_CLAIM_RE = re.compile(
    r"(?:\d[\d,]*(?:\.\d+)?\s*(?:km|킬로미터|만|억|배|배율|초|분|년|도|%|개|명)"
    r"|(?:몇|수십|수백|수천|수만|수억)\s*(?:년|km|킬로미터|배|도|개|명))",
    re.IGNORECASE,
)
_RISKY_CLAIM_PHRASES = (
    "선명도",
    "해상도",
    "노출",
    "궤도",
    "회전 속도",
    "공전",
    "반지름",
    "거리",
    "밀도",
    "각도",
    "반사광",
    "투영",
    "연구",
    "발표",
    "과학자",
    "증명",
    "관측 결과",
    "원인",
    "때문",
    "따라서",
    "영향",
    "결과적으로",
    "크기",
    "빛나",
    "밝",
    "뚜렷",
    "잘 보",
    "이번 달",
    "다음 달",
    "오늘 밤",
    "오늘",
    "이번",
    "다음",
    "추가",
    "앞으로",
    "다시",
    "변화",
    "다른 행성",
)
_PROMPT_LEAK_MARKERS = (
    "[작문 카드]",
    "[출력 규칙]",
    "[페르소나",
    "페르소나 심화",
    "관심 도메인",
    "좋은 발화 동작",
    "피해야 할 동작",
    "절대 쓰지 않는 표현",
    "target_comments",
    "json 객체",
    "json object",
)
_NEGATION_MARKERS = (
    "없다",
    "없어",
    "없는",
    "안 보",
    "보이지 않",
    "아니다",
    "아니야",
)
_COMPLETE_ENDINGS = (
    "했네",
    "했어",
    "보이네",
    "보여",
    "있네",
    "있어",
    "없네",
    "없어",
    "같네",
    "같아",
    "같음",
    "인가",
    "아닌가",
    "일까",
    "할까",
    "볼까",
    "맞나",
    "맞아",
    "맞음",
    "아님",
    "거야",
    "거네",
    "듯해",
    "듯",
    "임",
    "함",
    "셈",
    "다",
    "네",
    "요",
    "지",
    "냐",
    "까",
)


@dataclass(frozen=True)
class DraftReview:
    """Deterministic decision and repair context for one candidate."""

    accepted: bool
    issues: tuple[str, ...]
    repair_prompt: str
    metrics: dict[str, int]


def _compact(value: object) -> str:
    return "".join(str(value or "").casefold().split())


def _tokens(value: object) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(str(value or "")))


def _source_text(card: DraftCard) -> str:
    return " ".join(
        part
        for part in (card.brief.focus, *card.brief.facts)
        if str(part or "").strip()
    )


def _unsupported_claims(card: DraftCard, generated: str) -> tuple[str, ...]:
    source = _compact(_source_text(card))
    found: list[str] = []
    for match in _NUMBER_CLAIM_RE.finditer(generated):
        phrase = match.group(0).strip()
        if _compact(phrase) not in source:
            found.append(phrase)
    generated_compact = _compact(generated)
    for phrase in _RISKY_CLAIM_PHRASES:
        if _compact(phrase) in generated_compact and _compact(phrase) not in source:
            found.append(phrase)
    if naturalness.has_unsupported_personal_claim("", generated):
        found.append("개인 경험")
    return tuple(dict.fromkeys(found))


def _has_complete_ending(content: str) -> bool:
    value = str(content or "").strip().rstrip("ㅋㅎ")
    if not value:
        return False
    if value.endswith((".", "!", "?", "…", "。")):
        return True
    return any(value.endswith(ending) for ending in _COMPLETE_ENDINGS)


def _sentence_count(content: str) -> int:
    value = str(content or "").strip()
    if not value:
        return 0
    return max(1, len(re.findall(r"[.!?…。]+", value)))


def _build_repair_prompt(
    card: DraftCard,
    title: str,
    content: str,
    issues: tuple[str, ...],
) -> str:
    return "\n".join(
        (
            "[수정 카드]",
            "아래 초안은 게시 후보에서 거절됐다. 확인된 사실과 선택 페르소나의 말투·행동은 유지하고, 오류만 고쳐라.",
            f"- 검수 오류 코드: {', '.join(issues)}",
            f"- 이전 제목: {title}",
            f"- 이전 본문: {content}",
            "- 확인된 사실과 구체 앵커 밖의 수치·거리·원인·연구·발표·개인 경험은 삭제한다.",
            "- 제목은 짧아도 판단을 끝내고, 본문은 완결된 한 문장 이상으로 닫는다.",
            "- 내부 지시·페르소나 설명·검수 코드·메타 발언을 출력하지 않는다.",
            "- 최근 타겟 글이 없으므로 target_comments는 반드시 빈 배열([])이다.",
            card.writer_prompt(),
        )
    ).strip()


def review_draft(
    card: DraftCard,
    title: object,
    content: object,
    target_comments: object,
    *,
    recent_posts: object = None,
) -> DraftReview:
    """Review one local draft and fail closed on any quality contract breach."""

    title_text = str(title or "").strip()
    content_text = str(content or "").strip()
    combined = f"{title_text} {content_text}".strip()
    issues: list[str] = list(
        validate_draft(card, title_text, content_text, target_comments)
    )
    anchors = tuple(card.brief.anchors)
    anchor_hits = sum(1 for anchor in anchors if anchor and anchor in combined)
    body_tokens = _tokens(content_text)

    if not title_text or not content_text:
        if "empty_field" not in issues:
            issues.append("empty_field")
    if len(_tokens(title_text)) < 2 or len(title_text) < 4:
        issues.append("short_title")
    if len(body_tokens) < 4 or len(content_text) < 12:
        issues.append("short_sentence")
    if not _has_complete_ending(content_text):
        issues.append("incomplete_sentence")

    lowered = combined.casefold()
    if any(marker.casefold() in lowered for marker in _PROMPT_LEAK_MARKERS):
        issues.append("prompt_leak")

    unsupported = _unsupported_claims(card, combined)
    if unsupported:
        issues.append("unsupported_claim")

    source_compact = _compact(_source_text(card))
    if "함께" in source_compact and anchor_hits:
        combined_compact = _compact(combined)
        if any(_compact(marker) in combined_compact for marker in _NEGATION_MARKERS):
            issues.append("fact_contradiction")

    if recent_posts is None and target_comments:
        issues.append("comments_without_targets")

    naturalness_issues = naturalness.structure_failure_reasons(
        title_text,
        content_text,
    )
    if naturalness_issues:
        issues.append("unnatural_structure")

    unique_issues = tuple(dict.fromkeys(issues))
    metrics = {
        "anchor_hits": anchor_hits,
        "anchor_total": len(anchors),
        "title_tokens": len(_tokens(title_text)),
        "body_tokens": len(body_tokens),
        "sentence_count": _sentence_count(content_text),
        "unsupported_claims": len(unsupported),
        "naturalness_issues": len(naturalness_issues),
    }
    return DraftReview(
        accepted=not unique_issues,
        issues=unique_issues,
        repair_prompt=_build_repair_prompt(
            card,
            title_text,
            content_text,
            unique_issues,
        )
        if unique_issues
        else "",
        metrics=metrics,
    )


def grounded_fallback(card: DraftCard) -> tuple[str, str]:
    """Build a minimal grounded sentence when the local repair is unreliable.

    This is not a second creative writer.  It only restates the caller's
    confirmed fact and adds a tiny persona-safe tail, so a failed model cannot
    turn into an empty or unreviewed posting candidate.
    """

    fact = str(card.brief.facts[0] if card.brief.facts else card.brief.focus).strip()
    fact = re.sub(r"(?:보임|보인다|보여짐|있음)\s*$", "보이네", fact)
    fact = fact.rstrip(" .。!?")
    if not fact:
        fact = card.brief.focus.strip().rstrip(" .。!?")
    title_tokens = [
        token
        for token in card.brief.anchors
        if token not in {"보이", "있는", "함께", "사진"}
    ][:3]
    title = " ".join(title_tokens) or card.brief.focus[:24].strip()
    tails = {
        "neutral": " 이 장면이 먼저 눈에 들어오네.",
        "analytical": " 함께 보인다는 점만 확인되네.",
        "solution_proposer": " 우선 이 장면부터 보면 되겠다.",
        "hopium": " 아직은 이 장면만으로 충분히 보이네.",
        "topic_diverger": " 사진 속 이 장면부터 눈에 들어오네.",
        "experience_linker": " 사진을 보다 보니 장면이 오래 남네.",
        "possibility_mapper": " 이 장면이 눈에 남네.",
        "light_joker": " 한 화면에 같이 있네 ㅋㅋ.",
        "scene_noticer": "",
        "detail_extender": " 한 장면 안에 같이 보이는 점이 눈에 남네.",
    }
    return title, f"{fact}.{tails.get(card.tone, '')}".strip()


__all__ = ["DraftReview", "grounded_fallback", "review_draft"]
