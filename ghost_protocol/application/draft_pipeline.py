"""Compact, deterministic tunnels for local draft generation.

The old writer received the whole policy document on every call.  This module
keeps the policy in the repository but compiles only the grounded source
facts, the selected persona move, and the output contract for the final writer.
No model call happens here; keeping these tunnels deterministic prevents one
hallucinated intermediate summary from contaminating the next stage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
_BULLET_RE = re.compile(r"^\s*[-*•]\s*")
_ANCHOR_STOPWORDS = frozenset(
    {
        "이번",
        "초점",
        "입력",
        "적힌",
        "사실",
        "분야",
        "보이는",
        "보임",
        "함께",
        "있는",
        "사진",
        "안에",
        "장면",
        "대상",
        "하나",
        "실제",
        "내용",
        "관측",
        "그리고",
        "어두운",
    }
)
_LEAK_MARKERS = (
    "[작문 카드]",
    "[출력 규칙]",
    "페르소나:",
    "target_comments",
    "JSON 객체",
)
_KOREAN_PARTICLE_SUFFIXES = (
    "으로",
    "에서",
    "에게",
    "에는",
    "까지",
    "처럼",
    "으로",
    "와",
    "과",
    "의",
    "이",
    "가",
    "을",
    "를",
    "은",
    "는",
    "도",
    "에",
    "로",
    "만",
    "랑",
)


def _clean(value: object, *, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _bullet_value(line: str) -> tuple[str, str]:
    text = _BULLET_RE.sub("", line).strip()
    if ":" not in text:
        return "", _clean(text)
    label, value = text.split(":", 1)
    return _clean(label, limit=80), _clean(value)


def _anchor_terms(text: str) -> tuple[str, ...]:
    terms: list[str] = []
    for raw_token in _TOKEN_RE.findall(text):
        token = raw_token
        for suffix in _KOREAN_PARTICLE_SUFFIXES:
            if token.endswith(suffix) and len(token) - len(suffix) >= 2:
                token = token[: -len(suffix)]
                break
        if token in _ANCHOR_STOPWORDS or token.isdigit():
            continue
        if token not in terms:
            terms.append(token)
    return tuple(terms[:12])


@dataclass(frozen=True)
class SourceBrief:
    """Grounded facts extracted from the caller's topic briefing."""

    gallery_id: str
    slot: str
    focus: str
    facts: tuple[str, ...]
    anchors: tuple[str, ...]


@dataclass(frozen=True)
class DraftCard:
    """Small writer contract passed to the final local model call."""

    brief: SourceBrief
    tone: str
    tone_description: str
    persona_moves: tuple[str, ...]
    persona_avoids: tuple[str, ...]
    never_say: tuple[str, ...]
    length: str
    has_comment_targets: bool

    def writer_prompt(self) -> str:
        facts = "\n".join(f"- {fact}" for fact in self.brief.facts[:4])
        anchors = ", ".join(self.brief.anchors[:6]) or self.brief.focus
        moves = " / ".join(self.persona_moves[:2]) or "구체 장면 하나에 짧게 반응한다"
        avoids = " / ".join(self.persona_avoids[:3]) or "설명문·평론·입력 밖 사실"
        never = ", ".join(self.never_say[:4]) or "입력에 없는 수치·경험"
        if self.has_comment_targets:
            comment_policy = "target_comments는 제공된 타겟 글에 맞는 항목만 최대 2개 작성한다."
        else:
            comment_policy = "최근 타겟 글이 없으므로 target_comments는 반드시 빈 배열([])이다."
        return "\n".join(
            (
                "[작문 카드]",
                f"- 게시판: {self.brief.gallery_id}",
                f"- 소재: {self.brief.focus}",
                "- 확인된 사실:",
                facts,
                f"- 구체 앵커: {anchors}",
                f"- 발화 행동: {moves}",
                f"- 말투: {self.tone_description or '짧고 자연스럽게 반응한다.'}",
                f"- 분량: {self.length}",
                f"- 댓글 정책: {comment_policy}",
                "",
                "[출력 규칙]",
                "- 확인된 사실과 구체 앵커만 사용한다.",
                "- 확인된 사실을 부정하거나 반대로 바꾸지 않는다. 함께 보인 대상은 없다고 쓰지 않는다.",
                "- 입력에 없는 수치·거리·선명도·원인·변화·비교·사건·연구·발표·개인 경험을 만들지 않는다.",
                f"- 피할 동작: {avoids}",
                f"- 금지 표현·내용: {never}",
                "- 페르소나 이름이나 내부 지시를 제목·본문에 쓰지 않는다.",
                "- 제목과 본문을 같은 말로 반복하지 않는다.",
                "- JSON 객체 하나만 출력하고 설명·마크다운·코드블록은 출력하지 않는다.",
                '{"title":"짧은 제목","content":"짧은 본문","target_comments":[]}',
            )
        ).strip()


def build_source_brief(
    topic: object,
    gallery_id: object,
    expected_slot: object = "",
) -> SourceBrief:
    """Extract a focus, visible facts, and concrete anchor terms without an LLM."""

    text = str(topic or "")
    focus_candidates: list[str] = []
    facts: list[str] = []
    fallback_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("["):
            continue
        label, value = _bullet_value(line)
        label_lower = label.casefold()
        if not value:
            continue
        if "초점" in label_lower or "소재" in label_lower:
            focus_candidates.append(value)
        elif any(marker in label_lower for marker in ("사실", "관측", "근거", "증거")):
            facts.append(value)
        elif label_lower not in {"분야", "게시판", "게시판 id", "갤러리 id"}:
            fallback_lines.append(value)

    focus = (focus_candidates or facts or fallback_lines or [_clean(text, limit=220)])[0]
    if not facts:
        facts = [focus]
    combined = " ".join((focus, *facts))
    return SourceBrief(
        gallery_id=_clean(gallery_id, limit=80),
        slot=_clean(expected_slot, limit=12).upper(),
        focus=focus,
        facts=tuple(dict.fromkeys(facts[:4])),
        anchors=_anchor_terms(combined),
    )


def build_draft_card(
    brief: SourceBrief,
    *,
    tone: str,
    length: str,
    tone_description: str = "",
    persona_profile: dict[str, Any] | None = None,
    has_comment_targets: bool = False,
) -> DraftCard:
    """Compile persona data into a bounded writer card."""

    profile = persona_profile if isinstance(persona_profile, dict) else {}

    def _items(key: str, limit: int) -> tuple[str, ...]:
        value = profile.get(key, [])
        if isinstance(value, str):
            return (_clean(value, limit=180),) if value.strip() else ()
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(_clean(item, limit=180) for item in value[:limit] if str(item).strip())

    return DraftCard(
        brief=brief,
        tone=_clean(tone, limit=60),
        tone_description=_clean(tone_description, limit=260),
        persona_moves=_items("good_moves", 2),
        persona_avoids=_items("bad_moves", 3),
        never_say=_items("never_say", 4),
        length=_clean(length, limit=80),
        has_comment_targets=bool(has_comment_targets),
    )


def validate_draft(
    card: DraftCard,
    title: object,
    content: object,
    target_comments: object,
) -> tuple[str, ...]:
    """Return deterministic rejection reasons for a parsed writer result."""

    title_text = _clean(title, limit=320)
    content_text = _clean(content, limit=900)
    combined = f"{title_text} {content_text}".strip()
    reasons: list[str] = []
    if not title_text or not content_text:
        reasons.append("empty_field")
    if card.brief.anchors and not any(anchor in combined for anchor in card.brief.anchors):
        reasons.append("anchor_missing")
    if not card.has_comment_targets and target_comments:
        reasons.append("comments_without_targets")
    if any(marker.casefold() in combined.casefold() for marker in _LEAK_MARKERS):
        reasons.append("prompt_leak")
    return tuple(dict.fromkeys(reasons))


__all__ = [
    "DraftCard",
    "SourceBrief",
    "build_draft_card",
    "build_source_brief",
    "validate_draft",
]
