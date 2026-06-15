"""Rehearsal-only prompt and validation helpers.

The live/infinite path should keep strict duplicate and safety guards. Rehearsal
has a different job: observe whether a topic loop evolves naturally. If normal
topics are treated as hard bans during rehearsal, the loop collapses into empty
waves and the diagnostic signal disappears. This module keeps those decisions
explicit and testable.
"""

from __future__ import annotations

import re
from typing import Iterable


_STRONG_SAFETY_MARKERS = (
    "protected_group",
    "hard_hate",
    "혐오",
    "성희롱",
    "성적",
    "비하",
    "저격",
    "사칭",
    "개인 신상",
    "루머",
    "폭력",
    "자해",
    "불법",
)


def _clean_terms(values: Iterable[object], *, limit: int = 8) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if not text or text in seen:
            continue
        cleaned.append(text)
        seen.add(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def soft_cooldown_prompt_block(
    *,
    topics: Iterable[object] = (),
    title_keywords: Iterable[object] = (),
    starts: Iterable[object] = (),
) -> str:
    """Return a rehearsal-only cooldown block.

    Terms listed here are not forbidden. The model may keep the same live topic,
    but it must change the object, sentence shape, or local detail.
    """

    topic_terms = _clean_terms(topics, limit=6)
    title_terms = _clean_terms(title_keywords, limit=8)
    start_terms = _clean_terms(starts, limit=8)
    if not (topic_terms or title_terms or start_terms):
        return ""

    lines = [
        "[리허설 소프트 쿨다운]",
        "아래 단어는 금지가 아니라 반복 피로 신호다. 현재 흐름의 정상 소재라면 버리지 말고, 제목 첫머리·결론·대상·세부 장면을 바꿔서 이어간다.",
        "이 단어가 현재 브리핑/원본 앵커에 실제로 있으면 안전한 구체 장면으로 낮춰 사용해도 된다.",
        "다만 같은 제목 구조, 같은 질문, 같은 불평 문장은 다시 쓰지 않는다.",
    ]
    if topic_terms:
        lines.append(f"- 화제 쿨다운: {' / '.join(topic_terms)}")
    if title_terms:
        lines.append(f"- 제목어 쿨다운: {' / '.join(title_terms)}")
    if start_terms:
        lines.append(f"- 첫 어절 쿨다운: {' / '.join(start_terms)}")
    return "\n".join(lines)


def style_variety_prompt_block() -> str:
    """Return a compact style-diversity reminder for rehearsal batches."""

    return "\n".join(
        [
            "[리허설 문체 분산]",
            "10개 원고가 같은 사람이 쓴 것처럼 보이면 실패다.",
            "말끝, 길이, 질문 여부, 웃음 표지, 화살표 제목을 배치 안에서 섞는다.",
            "한 배치에서 같은 끝맺음(같음/듯/신기함/애매함/궁금함/좋겠다/아님?)을 2회 이상 반복하지 않는다.",
            "같은 소재를 다시 쓰면 제목 첫 단어, 문장 길이, 끝맺음, 몸통의 역할(장면/숫자/비교/경험/농담)을 반드시 바꾼다.",
            "불평·지적·교정문보다 장면 추가, 짧은 농담, 숫자 반응, 경험 축소, 다음 장면 예상을 우선한다.",
            "댓글은 원고의 구체 단어와 맞는 것만 붙인다. 다른 글의 떡밥을 억지로 끌어오지 않는다.",
        ]
    )


def analysis_rotation_notes(
    *,
    repeated_terms: Iterable[object] = (),
    failure_patterns: Iterable[object] = (),
    valid_count: int = 0,
    total_count: int = 10,
) -> str:
    """Return notes for the trend-analysis step of a rehearsal cycle.

    Rehearsal feeds generated drafts back into trend analysis. Without a
    counterweight, a few successful drafts can be mistaken for the whole board
    mood and then amplified again. Keep this block rehearsal-only and explicit.
    """

    repeated = _clean_terms(repeated_terms, limit=8)
    failures = _clean_terms(failure_patterns, limit=5)
    try:
        valid = max(0, int(valid_count))
    except (TypeError, ValueError):
        valid = 0
    try:
        total = max(1, int(total_count))
    except (TypeError, ValueError):
        total = 10
    low_success = valid < max(5, total // 2)
    if not (repeated or failures or low_success):
        return ""

    lines = [
        "[리허설 분석 보정]",
        "현재 입력에는 직전 AI 원고와 원본 앵커가 섞여 있다.",
        "직전 AI 원고의 반복 명사를 실제 게시판 전체 유행으로 과대평가하지 않는다.",
        "다음 사이클 분석은 한 소재를 키우는 것이 아니라 3~4개의 독립 소재군을 남기는 것이 목적이다.",
        "hot_topics는 같은 명사군을 여러 표현으로 나누지 말고 서로 다른 대상, 장면, 숫자, 댓글 반응으로 분산한다.",
        "generation_guidance에는 핵심 2개 + 옆 소재 2개 + 상시 분야 1개 배합을 우선 적는다.",
    ]
    if repeated:
        lines.append(
            "직전 과점 명사: "
            + " / ".join(repeated)
            + " — 다음 hot_topics에서는 이 명사군을 최대 1개 축으로만 둔다."
        )
    if failures:
        lines.append(
            "직전 실패 패턴: "
            + " / ".join(failures)
            + " — 실패 후보의 표현을 살리지 말고 원본 앵커의 다른 소재로 우회한다."
        )
    if low_success:
        lines.append(
            f"직전 성공률이 낮다({valid}/{total}). 성공 원고보다 원본 앵커와 안전한 상시 분야를 더 신뢰한다."
        )
    return "\n".join(lines)


def is_strong_safety_reason(reason: object) -> bool:
    text = str(reason or "")
    return any(marker in text for marker in _STRONG_SAFETY_MARKERS)


def is_recoverable_quality_reason(reason: object) -> bool:
    """Return whether rehearsal may keep a candidate as a diagnostic draft.

    We only recover narrow quality failures. Topic drift, external-material
    leakage, and safety reasons should still fail so the next cycle does not
    amplify unrelated or risky material.
    """

    text = str(reason or "")
    if not text or is_strong_safety_reason(text):
        return False
    if any(marker in text for marker in ("브리핑", "외부", "무관", "본래 주제")):
        return False
    if any(
        marker in text
        for marker in (
            "동일 제목",
            "같은 제목",
            "기존 원고",
            "제목 구조",
            "의미 중복",
            "핵심어 겹침",
            "같은 소재군",
            "소재군",
        )
    ):
        return False
    return any(
        marker in text
        for marker in (
            "메타",
            "빈도",
            "화제전환",
            "자연스러움",
            "화살표",
        )
    )


def allow_rehearsal_slot_drift(
    *,
    expected_slot: str,
    observed_slot: str,
    title: object = "",
    content: object = "",
) -> bool:
    """Return whether a slot mismatch should be diagnostic, not fatal."""

    expected = str(expected_slot or "").upper()
    observed = str(observed_slot or "").upper()
    if expected not in {"A", "B", "C", "R", "G"}:
        return False
    if not observed or observed == expected:
        return False
    text = f"{title or ''} {content or ''}".strip()
    return bool(text or observed == "CONTEXT")


def failure_pattern_label(reason: object) -> str:
    """Classify a failure reason without preserving toxic candidate wording."""

    text = str(reason or "")
    if "지정 슬롯" in text or "slot" in text.lower() or "슬롯" in text:
        return "slot_drift"
    if is_strong_safety_reason(text) or "안전" in text or "safety" in text.lower():
        return "safety_guard"
    if "중복" in text or "반복" in text or "유사" in text or "동일" in text:
        return "duplicate_loop"
    if "메타" in text or "빈도" in text or "화제전환" in text:
        return "meta_reaction"
    if "브리핑" in text or "외부" in text or "무관" in text:
        return "topic_drift"
    if "자연스러움" in text:
        return "naturalness"
    return "validation"
