"""Noise filters for analysis inputs.

The scraper should learn the community mood from ordinary conversation, not from
ads, macro/tool promotions, account sales, or contact-funnel spam.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class NoiseDecision:
    is_noise: bool
    score: int
    reasons: tuple[str, ...]


_SPACE_RE = re.compile(r"\s+")

_HARD_NOISE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"오토\s*사냥|자동\s*사냥", re.IGNORECASE), "auto_hunt"),
    (re.compile(r"작업장|리세계정|리세계", re.IGNORECASE), "account_farm"),
    (re.compile(r"(계정|아이디|캐릭|템|아이템)\s*(판매|삽니다|팝니다|매입|분양)", re.IGNORECASE), "account_trade"),
    (re.compile(r"(매크로|핵|프로그램)\s*(판매|공유|다운|구매|문의|추천|배포|사용법)", re.IGNORECASE), "tool_promo"),
    (re.compile(r"(무료\s*)?(체험|쿠폰|충전|대행|대리|홍보)\b", re.IGNORECASE), "promo_service"),
    (re.compile(r"(?:리버|river)\s*p\s*\.?\s*a\s*\.?\s*y|p\s*\.?\s*a\s*\.?\s*y\s*(문의|결제|충전|대행)", re.IGNORECASE), "payment_promo"),
)

_CONTACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"https?://|www\.|bit\.ly|t\.me|open\.kakao|kakao\.com", re.IGNORECASE), "link_or_contact"),
    (re.compile(r"텔레|텔레그램|카톡|카카오톡|오픈채팅|디코|디스코드|dm|쪽지", re.IGNORECASE), "contact_funnel"),
)

_PROMO_TERMS: tuple[str, ...] = (
    "광고",
    "홍보",
    "문의",
    "상담",
    "가입",
    "추천인",
    "레퍼럴",
    "이벤트",
    "할인",
    "무료",
    "쿠폰",
    "판매",
    "구매",
    "팝니다",
    "삽니다",
    "매입",
    "대행",
    "대리",
    "충전",
    "수익",
    "부업",
)

_TOOL_TERMS: tuple[str, ...] = (
    "매크로",
    "오토",
    "자동사냥",
    "오토사냥",
    "핵",
    "프로그램",
    "봇",
    "작업장",
    "리세계",
    "계정판매",
)

_SENSITIVE_TOPIC_CUES: tuple[str, ...] = (
    "인종",
    "민족",
    "국적",
    "차별",
    "혐오",
    "비하",
    "비인간화",
    "일반화",
)

_SEXUAL_TOPIC_CUES: tuple[str, ...] = (
    "성희롱",
    "성적 대상화",
    "성적인",
    "성적 상상",
    "신체 부위",
    "관계 추측",
    "선정적",
    "성희롱성",
    "여성 인물",
)

_PROTECTED_DIRECT_TERMS: tuple[str, ...] = (
    "동양인",
    "서양인",
    "백인",
    "흑인",
    "갈색인종",
    "중국인",
    "일본인",
    "한국인",
    "조선족",
    "유대인",
    "무슬림",
)

_HARD_HATE_TERMS: tuple[str, ...] = (
    "똥양인",
    # Often used as a regional slur in the collected board context. Treat it as
    # unsafe for generation even if the literal food meaning exists elsewhere.
    "홍어",
)

_DEHUMANIZING_TERMS: tuple[str, ...] = (
    "기생충",
    "종양",
    "바퀴",
    "모기",
)

_SEXUAL_OBJECTIFICATION_TERMS: tuple[str, ...] = (
    "뷰지",
    "벅지",
    "허벅지",
    "엉덩",
    "가슴",
    "몸매",
    "합방",
    "틱톡녀",
    "동희년",
    "유나년",
)

_SEXUALIZED_SOURCE_PHRASES: tuple[str, ...] = (
    "파트너이자 가족",
    "공동개발",
)

_GENERIC_ANALYSIS_KEYWORDS: tuple[str, ...] = (
    "오늘",
    "내가",
    "이유",
    "여기",
    "그냥",
    "사람",
    "사람들",
    "애들",
    "글들",
    "얘기",
)

_USER_DRAMA_CUES: tuple[str, ...] = (
    "특정 유저",
    "특정 인물",
    "닉네임",
    "저격",
    "뒷담",
    "친목",
    "로진짓",
    "약속 파기",
    "관련 불만",
)


def _normalize(text: str) -> str:
    return _SPACE_RE.sub(" ", str(text or "").strip().lower())


def requires_sexual_guard(topic: str) -> bool:
    """Return True when the source topic is sexual harassment/objectification."""

    normalized = _normalize(topic)
    if not normalized:
        return False
    return any(term in normalized for term in _SEXUAL_TOPIC_CUES)


def extract_sexualized_terms(text: str) -> list[str]:
    """Extract person labels that should not be reused in sexualized contexts."""

    raw = str(text or "")
    if not requires_sexual_guard(raw):
        return []

    candidates = re.findall(
        r"([가-힣A-Za-z0-9_]{2,18}(?:누나|눈나|녀|년|아씨|갑))",
        raw,
    )
    blocked = {"누나", "눈나"}
    clean: list[str] = []
    for candidate in candidates:
        term = str(candidate or "").strip(" .,;:!?()[]{}<>")
        normalized = _normalize(term)
        if not normalized or normalized in blocked:
            continue
        if term not in clean:
            clean.append(term)
    return clean


def extract_user_drama_terms(text: str) -> list[str]:
    """Extract likely nicknames from user-drama summaries."""

    raw = str(text or "")
    if not any(cue in raw for cue in _USER_DRAMA_CUES):
        return []

    candidates: list[str] = []
    for match in re.finditer(r"[\"'‘’“”]([^\"'‘’“”]{2,20})[\"'‘’“”]", raw):
        nearby = raw[max(0, match.start() - 40): min(len(raw), match.end() + 40)]
        if any(cue in nearby for cue in _USER_DRAMA_CUES):
            candidates.append(match.group(1))
    candidates.extend(
        re.findall(r"([가-힣A-Za-z0-9_]{2,16})\s*(?:로진짓|뒷담|저격)", raw)
    )
    candidates.extend(
        re.findall(r"특정\s*유저\s+([가-힣A-Za-z0-9_]{2,16})", raw)
    )
    candidates.extend(
        re.findall(r"특정\s*(?:유저|인물)\s*[\(（]([가-힣A-Za-z0-9_]{2,16})[\)）]", raw)
    )
    candidates.extend(
        re.findall(r"([가-힣A-Za-z0-9_]{2,16})\s*관련\s*불만", raw)
    )

    blocked = {
        "특정유저",
        "특정",
        "유저",
        "인물",
        "관련",
        "논란",
        "뒷담",
        "저격",
        "로진짓",
        "선관위",
        "민주당",
        "국힘",
        "국민의힘",
        "이재명",
        "윤석열",
    }
    clean: list[str] = []
    for candidate in candidates:
        term = str(candidate or "").strip(" .,;:!?()[]{}<>")
        normalized = _normalize(term)
        if not normalized or normalized in blocked or len(term) < 2:
            continue
        if any(cue in term for cue in _USER_DRAMA_CUES):
            continue
        if term not in clean:
            clean.append(term)
    return clean


def sanitize_user_drama_text(text: str, *, source_text: str = "") -> str:
    """Replace extracted nicknames in user-drama summaries with a neutral label."""

    value = str(text or "")
    for term in extract_user_drama_terms(source_text + "\n" + value):
        value = value.replace(term, "특정 유저")
    return value


def user_drama_generation_violations(text: str, *, topic: str = "") -> list[str]:
    """Detect generated drafts that directly reuse user-drama nicknames."""

    terms = extract_user_drama_terms(topic)
    normalized = _normalize(text)
    if not normalized or not terms:
        return []
    if any(_normalize(term) in normalized for term in terms):
        return ["named_user_drama"]
    return []


def requires_sensitive_guard(topic: str) -> bool:
    """Return True when the source topic needs protected-class guardrails."""

    normalized = _normalize(topic)
    if not normalized:
        return False
    guard_terms = (
        _SENSITIVE_TOPIC_CUES
        + _PROTECTED_DIRECT_TERMS
        + _HARD_HATE_TERMS
        + _DEHUMANIZING_TERMS
    )
    return any(term in normalized for term in guard_terms)


def sensitive_generation_violations(text: str, *, topic: str = "") -> list[str]:
    """Detect generated text that should be retried for sensitive topics."""

    normalized = _normalize(text)
    if not normalized:
        return []

    violations: list[str] = []
    if any(term in normalized for term in _HARD_HATE_TERMS):
        violations.append("hard_hate_term")

    if requires_sensitive_guard(topic):
        if any(term in normalized for term in _PROTECTED_DIRECT_TERMS):
            violations.append("protected_group_direct")
        if any(term in normalized for term in _DEHUMANIZING_TERMS):
            violations.append("dehumanizing_metaphor")

    if requires_sexual_guard(topic):
        if any(term in normalized for term in _SEXUAL_OBJECTIFICATION_TERMS):
            violations.append("sexual_objectification_term")
        if any(_normalize(term) in normalized for term in extract_sexualized_terms(topic)):
            violations.append("sexualized_person_label")
        if any(_normalize(term) in normalized for term in _SEXUALIZED_SOURCE_PHRASES):
            violations.append("sexualized_source_phrase")

    violations.extend(user_drama_generation_violations(text, topic=topic))

    return list(dict.fromkeys(violations))


def sanitize_sensitive_target_comments(
    items: Iterable[dict],
    *,
    topic: str,
) -> list[dict]:
    """Remove risky generated comments while keeping safe post targets."""

    clean: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        comment = str(item.get("comment", ""))
        if sensitive_generation_violations(comment, topic=topic):
            continue
        clean.append(item)
    return clean


def sanitize_analysis_keywords(
    keywords: Iterable[str],
    *,
    source_text: str = "",
) -> list[str]:
    """Drop raw slurs, direct protected-group labels, and filler keywords."""

    sensitive = requires_sensitive_guard(source_text)
    sexual = requires_sexual_guard(source_text)
    user_drama_terms = [_normalize(term) for term in extract_user_drama_terms(source_text)]
    sexual_terms = [_normalize(term) for term in extract_sexualized_terms(source_text)]
    clean: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        value = str(keyword or "").strip()
        normalized = _normalize(value)
        if not normalized or normalized in seen:
            continue
        if normalized in _GENERIC_ANALYSIS_KEYWORDS:
            continue
        if any(term in normalized for term in _HARD_HATE_TERMS):
            continue
        if any(term and term in normalized for term in user_drama_terms):
            continue
        if sensitive and any(
            term in normalized
            for term in (_PROTECTED_DIRECT_TERMS + _DEHUMANIZING_TERMS)
        ):
            continue
        if sexual and any(
            term in normalized
            for term in (
                _SEXUAL_OBJECTIFICATION_TERMS
                + _SEXUALIZED_SOURCE_PHRASES
            )
        ):
            continue
        if sexual and any(term and term in normalized for term in sexual_terms):
            continue
        seen.add(normalized)
        clean.append(value)
    return clean


def classify_noise_text(text: str, *, threshold: int = 3) -> NoiseDecision:
    """Return whether a text looks like ad/macro/farm noise.

    The scoring is intentionally conservative for common words such as "핵" or
    "봇", but hard-blocks recurring spam materials like auto-hunting tools.
    """

    normalized = _normalize(text)
    if not normalized:
        return NoiseDecision(False, 0, ())

    score = 0
    reasons: list[str] = []

    for pattern, reason in _HARD_NOISE_PATTERNS:
        if pattern.search(normalized):
            score += 4
            reasons.append(reason)

    for pattern, reason in _CONTACT_PATTERNS:
        if pattern.search(normalized):
            score += 2
            reasons.append(reason)

    promo_hits = [term for term in _PROMO_TERMS if term in normalized]
    tool_hits = [term for term in _TOOL_TERMS if term in normalized]
    if promo_hits:
        score += min(3, len(promo_hits))
        reasons.append("promo_terms")
    if tool_hits:
        score += min(2, len(tool_hits))
        reasons.append("tool_terms")

    if promo_hits and tool_hits:
        score += 2
        reasons.append("promo_tool_combo")

    return NoiseDecision(score >= threshold, score, tuple(dict.fromkeys(reasons)))


def filter_noise_strings(items: Iterable[str]) -> tuple[list[str], dict]:
    """Filter noisy strings and return (clean_items, stats)."""

    clean: list[str] = []
    removed: list[dict] = []
    for item in items:
        decision = classify_noise_text(item)
        if decision.is_noise:
            removed.append({
                "text": str(item),
                "score": decision.score,
                "reasons": list(decision.reasons),
            })
        else:
            clean.append(item)

    return clean, {
        "removed_count": len(removed),
        "removed_samples": removed[:10],
    }


def summarize_noise_decisions(decisions: Sequence[NoiseDecision]) -> dict:
    """Build compact stats for post-level filtering."""

    reason_counts: dict[str, int] = {}
    for decision in decisions:
        for reason in decision.reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "removed_count": len(decisions),
        "reason_counts": reason_counts,
    }
