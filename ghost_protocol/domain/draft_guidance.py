"""Per-wave draft guidance for community-style batch generation.

The prompt already explains the broad writing rules. This module gives each
wave a smaller assignment so a batch does not collapse into the same noun and
the same reaction pattern.
"""

from __future__ import annotations

import math
import re

from ghost_protocol import content_filter
from ghost_protocol.domain import gallery_purpose
from ghost_protocol.domain import naturalness

ANGLE_LANES: tuple[tuple[str, str], ...] = naturalness.angle_lanes()
SLOT_SEQUENCE: tuple[str, ...] = naturalness.slot_sequence()
SPEECH_SHAPES: tuple[tuple[str, str], ...] = naturalness.speech_shapes()

_SOURCE_SLOT_STOPWORDS = {
    "오늘", "요즘", "이거", "그거", "저거", "그냥", "진짜", "솔직히", "근데",
    "아니", "다들", "사람", "사람들", "글", "글들", "댓글", "제목", "갤러리",
    "게시판", "관련", "논란", "이야기", "얘기", "특정", "유저", "인물",
    "반응", "표현", "상황", "문제", "가능성", "주장", "평가", "여부",
}


def extract_seed_slots(topic: object) -> dict[str, str]:
    """Return [A]/[B]/[C] seed slots from a briefing string."""

    raw = str(topic or "")
    slots: dict[str, str] = {}
    for label, text in re.findall(r"\[([ABC]):\s*([^\]]+)\]", raw):
        clean = " ".join(text.split())
        if clean:
            slots[label] = clean
    return slots


def _topic_tokens(text: object) -> set[str]:
    tokens: set[str] = set()
    for raw_token in re.findall(
        r"[0-9a-z가-힣]{2,}",
        str(text or "").casefold(),
    ):
        token = raw_token
        for suffix in ("으로", "에서", "에게", "까지", "부터", "처럼", "과", "와", "은", "는", "이", "가", "을", "를", "도", "만", "의"):
            if len(token) > len(suffix) + 1 and token.endswith(suffix):
                token = token[: -len(suffix)]
                break
        if token in _SOURCE_SLOT_STOPWORDS or token.isdigit() or len(token) < 2:
            continue
        tokens.add(token)
    return tokens


def topic_family_tokens(text: object) -> frozenset[str]:
    """Return stable content tokens used to cluster semantically close lanes."""

    return frozenset(_topic_tokens(text))


def _related_token(left: str, right: str) -> bool:
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    return len(shorter) >= 2 and longer.startswith(shorter)


def same_topic_family(
    left: object,
    right: object,
) -> bool:
    """Return True when two token sets represent the same concrete topic family."""

    left_tokens = (
        set(left)
        if isinstance(left, (set, frozenset, tuple, list))
        else set(topic_family_tokens(left))
    )
    right_tokens = (
        set(right)
        if isinstance(right, (set, frozenset, tuple, list))
        else set(topic_family_tokens(right))
    )
    if not left_tokens or not right_tokens:
        return False
    related_pairs = {
        (left_token, right_token)
        for left_token in left_tokens
        for right_token in right_tokens
        if _related_token(left_token, right_token)
    }
    if not related_pairs:
        return False
    related_left = {pair[0] for pair in related_pairs}
    related_right = {pair[1] for pair in related_pairs}
    coverage = max(
        len(related_left) / len(left_tokens),
        len(related_right) / len(right_tokens),
    )
    return coverage >= 0.5 or any(
        min(len(left_token), len(right_token)) >= 4
        for left_token, right_token in related_pairs
    )


def topic_family_cap(total_count: int) -> int:
    """Limit one semantic family to roughly 15% of a batch."""

    total = max(1, int(total_count or 1))
    return max(1, min(3, math.ceil(total * 0.15)))


def topic_family_usage(
    family_tokens: object,
    successful_families: tuple[object, ...] | list[object] = (),
) -> int:
    """Count successful drafts that belong to a semantic topic family."""

    return sum(
        1
        for successful in successful_families
        if same_topic_family(family_tokens, successful)
    )


def source_side_candidates(
    topic: object,
    source_posts: tuple[dict, ...] | list[dict] = (),
    *,
    gallery_id: str = "",
) -> list[dict]:
    """Return real source posts that add a topic outside the A/B/C briefing axis."""

    briefing_tokens = _topic_tokens(" ".join(extract_seed_slots(topic).values()))
    candidates: list[dict] = []
    seen_titles: set[str] = set()
    for post in source_posts or ():
        if not isinstance(post, dict):
            continue
        title = " ".join(
            str(post.get("title") or post.get("source_title") or "").split()
        )
        content = " ".join(
            str(post.get("content") or post.get("body") or "").split()
        )
        if not title:
            continue
        source_text = f"{title}\n{content}"
        if content_filter.classify_noise_text(source_text).is_noise:
            continue
        if content_filter.sensitive_generation_violations(source_text, topic=source_text):
            continue
        if naturalness.has_direct_person_callout(title, content):
            continue
        if naturalness.has_hard_meta_reaction(title, content):
            continue
        title_key = title.casefold()
        if title_key in seen_titles:
            continue
        source_tokens = _topic_tokens(f"{title} {content}")
        if not source_tokens:
            continue
        if gallery_id and gallery_purpose.text_matches(gallery_id, title, content):
            continue
        # R exists to open a real side topic, not to reword the briefing slots.
        if briefing_tokens and source_tokens <= briefing_tokens:
            continue
        seen_titles.add(title_key)
        candidates.append(
            {
                "post_no": str(post.get("post_no") or "").strip(),
                "title": title,
                "content": content,
            }
        )
    return candidates


def available_slots(
    topic: object,
    *,
    gallery_id: str = "",
    source_posts: tuple[dict, ...] | list[dict] = (),
    purpose_slot_enabled: bool = True,
) -> tuple[str, ...]:
    """Return generation lanes backed by actual input data."""

    seed_slots = extract_seed_slots(topic)
    slots = [label for label in ("A", "B", "C") if label in seed_slots]
    if source_side_candidates(topic, source_posts, gallery_id=gallery_id):
        slots.append("R")
    has_source_posts = bool(source_posts)
    if purpose_slot_enabled and gallery_purpose.purpose_candidates(
        gallery_id,
        source_posts,
        allow_fallback=not has_source_posts,
    ):
        slots.append("G")
    return tuple(slots) or ("context",)


def slot_quotas(
    total_count: int,
    topic: object,
    *,
    gallery_id: str = "",
    source_posts: tuple[dict, ...] | list[dict] = (),
    purpose_slot_enabled: bool = True,
) -> dict[str, int]:
    """Split a batch across briefing, real-source, and gallery-purpose lanes."""

    total = max(1, int(total_count or 1))
    slots = available_slots(
        topic,
        gallery_id=gallery_id,
        source_posts=source_posts,
        purpose_slot_enabled=purpose_slot_enabled,
    )
    quotas = {slot: 0 for slot in slots}
    reserved = 0
    if "G" in slots:
        quotas["G"] = gallery_purpose.target_count(gallery_id, total)
        reserved += quotas["G"]
    if "R" in slots:
        quotas["R"] = min(
            max(1, math.ceil(total * 0.20)),
            max(0, total - reserved),
        )
        reserved += quotas["R"]

    general_slots = [slot for slot in slots if slot not in {"G", "R"}]
    remaining_total = max(0, total - reserved)
    if general_slots:
        base, remainder = divmod(remaining_total, len(general_slots))
        for index, slot in enumerate(general_slots):
            quotas[slot] = base + (1 if index < remainder else 0)
    elif reserved < total:
        fallback_slot = "G" if "G" in slots else slots[0]
        quotas[fallback_slot] += total - reserved
    return quotas


def slot_schedule(
    total_count: int,
    topic: object,
    *,
    gallery_id: str = "",
    source_posts: tuple[dict, ...] | list[dict] = (),
    purpose_slot_enabled: bool = True,
) -> tuple[str, ...]:
    """Build an interleaved quota schedule instead of repeating one hot slot."""

    quotas = slot_quotas(
        total_count,
        topic,
        gallery_id=gallery_id,
        source_posts=source_posts,
        purpose_slot_enabled=purpose_slot_enabled,
    )
    preferred_order = ("A", "B", "R", "C", "G", "context")
    remaining = dict(quotas)
    schedule: list[str] = []
    while any(value > 0 for value in remaining.values()):
        for slot in preferred_order:
            if remaining.get(slot, 0) <= 0:
                continue
            schedule.append(slot)
            remaining[slot] -= 1
    return tuple(schedule)


def select_slot(
    wave_index: int,
    total_count: int,
    topic: object,
    *,
    gallery_id: str = "",
    source_posts: tuple[dict, ...] | list[dict] = (),
    purpose_slot_enabled: bool = True,
    success_counts: dict[str, int] | None = None,
    excluded_slots: tuple[str, ...] | list[str] = (),
) -> str:
    """Select the next underfilled slot, rotating away from failed attempts."""

    schedule = slot_schedule(
        total_count,
        topic,
        gallery_id=gallery_id,
        source_posts=source_posts,
        purpose_slot_enabled=purpose_slot_enabled,
    )
    quotas = slot_quotas(
        total_count,
        topic,
        gallery_id=gallery_id,
        source_posts=source_posts,
        purpose_slot_enabled=purpose_slot_enabled,
    )
    counts = success_counts or {}
    excluded = set(excluded_slots)
    start = (max(1, int(wave_index or 1)) - 1) % len(schedule)
    rotated = schedule[start:] + schedule[:start]

    for slot in rotated:
        if slot in excluded:
            continue
        if counts.get(slot, 0) < quotas.get(slot, 0):
            return slot
    for slot in rotated:
        if slot not in excluded:
            return slot
    return schedule[start]


def plan_wave_guidance(
    wave_index: int,
    total_count: int,
    topic: object,
    *,
    persona_key: str = "",
    gallery_id: str = "",
    source_posts: tuple[dict, ...] | list[dict] = (),
    purpose_slot_enabled: bool = True,
    slot_override: str = "",
    source_offset: int = 0,
    persona_occurrence: int = 0,
) -> dict[str, str]:
    """Build a compact slot/angle assignment for one generation wave."""

    if wave_index <= 0:
        wave_index = 1

    slots = extract_seed_slots(topic)
    purpose_profile = gallery_purpose.get_profile(gallery_id)
    source_candidates = source_side_candidates(
        topic,
        source_posts,
        gallery_id=gallery_id,
    )
    purpose_candidates = gallery_purpose.purpose_candidates(
        gallery_id,
        source_posts,
        allow_fallback=not bool(source_posts),
    )
    progress = (wave_index - 1) / max(total_count - 1, 1)
    requested_slot = str(slot_override or "").strip().upper()
    scheduled_slots = slot_schedule(
        total_count,
        topic,
        gallery_id=gallery_id,
        source_posts=source_posts,
        purpose_slot_enabled=purpose_slot_enabled,
    )
    if not requested_slot:
        requested_slot = scheduled_slots[wave_index - 1]
    valid_slots = available_slots(
        topic,
        gallery_id=gallery_id,
        source_posts=source_posts,
        purpose_slot_enabled=purpose_slot_enabled,
    )
    if requested_slot not in valid_slots:
        requested_slot = next((label for label in ("A", "B", "C") if label in slots), "context")

    angle_key, angle_instruction = ANGLE_LANES[(wave_index - 1) % len(ANGLE_LANES)]
    shape_key, shape_instruction = SPEECH_SHAPES[(wave_index - 1) % len(SPEECH_SHAPES)]

    persona_angle_preferences = naturalness.persona_angle_preferences()
    if persona_key in persona_angle_preferences:
        preferences = persona_angle_preferences[persona_key]
        angle_key = preferences[max(0, int(persona_occurrence)) % len(preferences)]
        angle_instruction = naturalness.angle_instruction(angle_key)

    source_post: dict = {}
    if requested_slot == "R" and source_candidates:
        source_post = source_candidates[
            (wave_index - 1 + max(0, int(source_offset))) % len(source_candidates)
        ]
    purpose_offset = max(0, int(source_offset))
    if requested_slot == "G" and not slot_override:
        purpose_offset = max(
            0,
            sum(1 for slot in scheduled_slots[:wave_index] if slot == "G") - 1,
        )
    slot_text = (
        purpose_candidates[
            purpose_offset % len(purpose_candidates)
        ]
        if requested_slot == "G" and purpose_candidates
        else str(purpose_profile.get("topic_label") or "").strip()
    ) if requested_slot == "G" else (
        str(source_post.get("title") or "").strip()
        if requested_slot == "R"
        else slots.get(requested_slot, "")
    )
    if requested_slot == "G":
        slot_line = (
            f"[G] 갤러리 본래 주제 '{slot_text}'의 구체 대상·현상·장면 하나를 잡는다."
        )
    elif requested_slot == "R":
        slot_line = (
            f"[R] 실제 최근 글 '{slot_text}'의 소재로 독립 글을 시작한다. "
            "브리핑 화제로 억지 연결하지 않는다."
        )
    elif requested_slot == "context":
        slot_line = "씨앗 슬롯이 없으면 브리핑의 구체 명사 1개만 잡는다."
    else:
        slot_line = f"[{requested_slot}] 슬롯의 '{slot_text}'에서 구체 표현·기준·장면 하나만 잡는다."

    phase_line = naturalness.phase_instruction(progress)

    purpose_guidance = ""
    if requested_slot == "G":
        purpose_guidance = (
            gallery_purpose.guidance_block(
                gallery_id,
                source_posts,
                focus=slot_text,
            )
            + "\n- [G]는 현재 브리핑 밖이어도 허용되는 유일한 슬롯이다. "
            "다른 화제로 넓히지 말고 본래 주제 한 가지에만 머문다.\n"
            "- [G] 제목과 본문에 이번 초점의 구체 명사 또는 관측 장면을 반드시 넣는다.\n"
            "- [G]에서 갤러리 이름, 이름값, 본래 주제 복귀, 뜻 질문은 금지한다.\n"
        )
    elif requested_slot == "R":
        source_body = str(source_post.get("content") or "").strip()
        purpose_guidance = (
            "[R: 실제 최근 글의 옆 소재]\n"
            f"- 원본 제목: {slot_text}\n"
            + (f"- 원본 본문: {source_body[:180]}\n" if source_body else "")
            + "- 원본에 실제로 있는 대상·장면·숫자만 사용한다. "
            "핫토픽이 지겹다는 말이나 화제전환 선언은 쓰지 않는다.\n"
        )

    guidance = (
        f"[🎚️ 이번 Wave 역할]\n"
        f"- 목표 슬롯: {slot_line}\n"
        f"- 발화 각도: {angle_instruction}\n"
        f"- 제목 구조: {shape_instruction}\n"
        f"- 배치 흐름: {phase_line}\n"
        "- 기본은 평서형이다. 질문은 원본 자체가 구체 질문이고 배치 질문 상한이 남았을 때만 한 번 쓴다.\n"
        "- `가능?`, `현실 가능함?`, `진짜냐`, `진짜였나`, `언제부터`, `무슨 뜻`, `사용 맥락`, `뭐 바뀐` 같은 범용 확인 질문은 평서형 작은 판단으로 바꾼다.\n"
        "- 제목을 `...해도`, `...좋아지면`, `...가능하단 거`, `...솔직히 좀`처럼 연결어에서 멈추지 말고 짧은 결론까지 닫는다.\n"
        "- `난 10만 날려봄`, `당첨된 적 없다`처럼 입력에 없는 1인칭 손실·당첨·경험은 만들지 않는다. 숫자나 결과만 말한다.\n"
        "- 이전 제목과 명사나 결론이 겹치면 어미를 바꾸지 말고 장면·기준·결과를 바꾼다.\n"
        "- 빈도 불평, 뜻 질문, 게시판 요약 대신 장면 관찰·디테일·가벼운 농담·"
        "생활 연결·다음 장면 예상 중 하나를 보탠다.\n"
        "- 불평·불만·지적·책임 추궁은 soft_counter가 지정된 경우가 아니면 쓰지 않는다.\n"
        "- 위험한 원문은 도덕적 비판문으로 바꾸지 말고 안전한 옆 대상·장면·사실로 이동한다.\n"
        "- 원본 글/댓글 세트의 길이와 생략 방식을 우선하고 본문은 한 줄을 기본으로 한다.\n"
        f"{purpose_guidance}"
        "- 마지막 시도도 품질 기준을 낮추지 않는다. 통과하지 못하면 보충 생성으로 넘긴다."
    )
    return {
        "slot": requested_slot,
        "slot_text": slot_text,
        "angle_key": angle_key,
        "shape_key": shape_key,
        "guidance": guidance,
        "total_count": str(total_count),
        "source_post_no": str(source_post.get("post_no") or ""),
        "source_title": str(source_post.get("title") or ""),
        "source_content": str(source_post.get("content") or ""),
        "family_tokens": tuple(sorted(topic_family_tokens(slot_text))),
    }


def select_diverse_plan(
    wave_index: int,
    total_count: int,
    topic: object,
    *,
    persona_key: str = "",
    persona_occurrence: int = 0,
    gallery_id: str = "",
    source_posts: tuple[dict, ...] | list[dict] = (),
    purpose_slot_enabled: bool = True,
    success_counts: dict[str, int] | None = None,
    successful_families: tuple[object, ...] | list[object] = (),
    excluded_families: tuple[object, ...] | list[object] = (),
) -> dict[str, str]:
    """Choose an underused semantic family before filling a slot quota."""

    schedule = slot_schedule(
        total_count,
        topic,
        gallery_id=gallery_id,
        source_posts=source_posts,
        purpose_slot_enabled=purpose_slot_enabled,
    )
    quotas = slot_quotas(
        total_count,
        topic,
        gallery_id=gallery_id,
        source_posts=source_posts,
        purpose_slot_enabled=purpose_slot_enabled,
    )
    counts = success_counts or {}
    start = (max(1, int(wave_index or 1)) - 1) % len(schedule)
    rotated = schedule[start:] + schedule[:start]
    unique_slots = tuple(dict.fromkeys(rotated))
    source_count = max(
        1,
        len(source_side_candidates(topic, source_posts, gallery_id=gallery_id)),
    )
    purpose_count = max(
        1,
        len(
            gallery_purpose.purpose_candidates(
                gallery_id,
                source_posts,
                allow_fallback=not bool(source_posts),
            )
        ),
    )
    family_cap = topic_family_cap(total_count)
    candidates: list[tuple[tuple[int, int, int, int, int], dict[str, str]]] = []

    for rotation_index, slot in enumerate(unique_slots):
        if slot == "R":
            offsets = range(source_count)
        elif slot == "G":
            offsets = range(purpose_count)
        else:
            offsets = range(1)
        for source_offset in offsets:
            plan = plan_wave_guidance(
                wave_index,
                total_count,
                topic,
                persona_key=persona_key,
                persona_occurrence=persona_occurrence,
                gallery_id=gallery_id,
                source_posts=source_posts,
                purpose_slot_enabled=purpose_slot_enabled,
                slot_override=slot,
                source_offset=source_offset,
            )
            family_tokens = plan.get("family_tokens", ())
            if any(
                same_topic_family(family_tokens, excluded)
                for excluded in excluded_families
            ):
                continue
            usage = topic_family_usage(family_tokens, successful_families)
            underfilled = counts.get(slot, 0) < quotas.get(slot, 0)
            score = (
                1 if usage >= family_cap else 0,
                usage,
                0 if underfilled else 1,
                rotation_index,
                source_offset,
            )
            candidates.append((score, plan))

    if not candidates and excluded_families:
        return select_diverse_plan(
            wave_index,
            total_count,
            topic,
            persona_key=persona_key,
            persona_occurrence=persona_occurrence,
            gallery_id=gallery_id,
            source_posts=source_posts,
            purpose_slot_enabled=purpose_slot_enabled,
            success_counts=success_counts,
            successful_families=successful_families,
        )
    if candidates:
        return min(candidates, key=lambda item: item[0])[1]
    return plan_wave_guidance(
        wave_index,
        total_count,
        topic,
        persona_key=persona_key,
        persona_occurrence=persona_occurrence,
        gallery_id=gallery_id,
        source_posts=source_posts,
        purpose_slot_enabled=purpose_slot_enabled,
    )
