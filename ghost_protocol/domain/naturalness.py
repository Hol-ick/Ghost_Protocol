"""Config-driven naturalness policy for draft generation.

The project used to scatter "awkwardness" rules across prompts, personas,
judges, and Streamlit validators. This module centralizes those rules in
``prompts/naturalness_policy.json`` so future tuning can happen by changing the
policy file instead of adding one-off hardcoded phrases.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable

from ghost_protocol import prompt_manager as pm


_DEFAULT_ANGLE_LANES: tuple[tuple[str, str], ...] = (
    ("insider_usage", "용어·밈의 용례·뉘앙스·타이밍이 맞는지 툭 찌른다."),
    ("money_or_responsibility", "돈·책임·대가처럼 사람들이 따지는 기준 하나만 잡는다."),
    ("timing", "말이 튄 타이밍이나 흐름 전환을 의심하되 확정하지 않는다."),
    ("small_rebuttal", "다수 반응을 살짝 낮춰 잡거나 반박한다."),
    ("fatigue", "지친 반응을 쓰되 어떤 표현·장면·기준이 피곤한지 말한다."),
    ("side_detail", "메인 떡밥 옆의 작은 표현·숫자·장면으로 새 글을 바로 시작한다."),
    ("tiny_solution", "작은 행동 제안 하나만 던진다."),
    ("scene_recall", "앞 장면과 지금 장면의 차이를 짧게 진술한다."),
)

_DEFAULT_SPEECH_SHAPES: tuple[tuple[str, str], ...] = (
    ("object_first", "제목 첫머리는 좁은 물체로 시작한다."),
    ("half_context", "이미 앞 대화를 본 사람처럼 설명을 생략한다."),
    ("criterion_narrow", "판단 기준은 대상 수치·표현·행동 하나로 좁힌다."),
    ("soft_counter", "반박은 낮게 걸어 둔다."),
    ("side_start", "옆 소재는 장면 하나로 바로 시작한다."),
    ("low_visibility", "이목을 끄는 호출·확신 대신 낮은 반응으로 쓴다."),
)


def _compact(text: object) -> str:
    return "".join(str(text or "").split()).lower()


@lru_cache(maxsize=1)
def load_policy() -> dict:
    """Load the naturalness policy from prompts/.

    Returning an empty dict on malformed data keeps generation usable while
    tests catch policy regressions.
    """

    data = pm.load_json("naturalness_policy.json")
    return data if isinstance(data, dict) else {}


def _list_at(*keys: str) -> list:
    current: object = load_policy()
    for key in keys:
        if not isinstance(current, dict):
            return []
        current = current.get(key)
    return current if isinstance(current, list) else []


def pattern_list(group: str) -> tuple[str, ...]:
    return tuple(str(item) for item in _list_at("patterns", group) if str(item).strip())


def has_pattern(group: str, title: str, content: str = "") -> bool:
    combined = _compact(f"{title} {content}")
    return any(_compact(pattern) in combined for pattern in pattern_list(group))


def has_concrete_hook(title: str, content: str = "") -> bool:
    return has_pattern("concrete_hooks", title, content)


def has_newbie_definition_question(title: str, content: str = "") -> bool:
    return has_pattern("newbie_definition_question", title, content)


def has_forced_topic_switch(title: str, content: str = "") -> bool:
    return has_pattern("forced_topic_switch", title, content)


def has_generic_meta_reaction(title: str, content: str = "") -> bool:
    if has_concrete_hook(title, content):
        return False
    return has_pattern("generic_meta_reaction", title, content)


def has_hard_meta_reaction(title: str, content: str = "") -> bool:
    return has_pattern("hard_meta_reaction", title, content) or has_pattern(
        "forced_topic_switch", title, content
    )


def has_abstract_moderator_phrasing(title: str, content: str = "") -> bool:
    """Detect titles that sound like a moderator summarizing the board.

    These are not always unsafe, but they read less like a regular board user:
    broad subject + generic question/summary. Kept policy-driven so future
    examples can be tuned without touching validators.
    """

    return has_pattern("abstract_moderator_phrasing", title, content)


def has_outsider_moderation_phrasing(title: str, content: str = "") -> bool:
    """Detect board-wide critique that reads like an outside reviewer."""

    return has_pattern("outsider_moderation_phrasing", title, content)


def has_direct_person_callout(title: str, content: str = "") -> bool:
    """Detect drafts that directly address or single out a board user."""

    if has_pattern("personal_callout", title, content):
        return True
    value = str(title or "").strip()
    if not value:
        return False
    # Nickname + vocative particle + suspicious verb/question frame.
    return bool(
        re.match(
            r"^[가-힣A-Za-z0-9_]{2,12}(?:아|야)\s*(?:왜|뭐|그만|좀|쟤|얘|너)",
            value,
        )
    )


def has_complaint_judgment(title: str, content: str = "") -> bool:
    """Detect low-value complaint/critique conclusions that stand out."""

    return has_pattern("complaint_judgment", title, content)


def has_thin_broad_subject(title: str, content: str = "") -> bool:
    """Return True for broad topics that lack a narrow conversational object."""

    title_compact = _compact(title)
    if not any(_compact(pattern) in title_compact for pattern in pattern_list("thin_broad_subjects")):
        return False
    # Concrete hooks in the body can save a broad title only if the title itself
    # names a narrow object. Otherwise it still feels like a review prompt.
    title_hooks = ("숫자", "차이", "표", "지역", "서울", "경북", "대구", "개표", "방송", "득표", "출구")
    return not any(_compact(hook) in title_compact for hook in title_hooks)


def has_assertive_rumor_question(title: str, content: str = "") -> bool:
    """Detect questions that push an unverified claim as the expected answer."""

    return has_pattern("assertive_rumor_question", title, content)


def has_attention_grabbing(
    title: str,
    content: str = "",
    *,
    allow_long_laugh: bool = False,
) -> bool:
    """Detect drafts that try to pull attention instead of blending into flow."""

    combined = _compact(f"{title} {content}")
    for pattern in pattern_list("attention_grabbing"):
        compact_pattern = _compact(pattern)
        if allow_long_laugh and compact_pattern and set(compact_pattern) <= {"ㅋ", "ㅎ"}:
            continue
        if compact_pattern in combined:
            return True
    return False


def has_explanatory_ai_phrasing(title: str, content: str = "") -> bool:
    """Detect drafts that sound like a briefing or policy note, not a post."""

    return has_pattern("explanatory_ai_phrasing", title, content)


def has_incomplete_title(title: str) -> bool:
    """Return True when a title stops before delivering its reaction.

    Short nominal titles are common on boards, so this check is intentionally
    limited to policy-managed endings that clearly leave a judgment hanging.
    """

    compact_title = _compact(title)
    return any(
        compact_title.endswith(_compact(ending))
        for ending in pattern_list("incomplete_title_endings")
        if _compact(ending)
    )


def has_unsupported_personal_claim(title: str, content: str = "") -> bool:
    """Detect fabricated-looking first-person experience claims.

    The prompt can ask the model not to invent lived experience, but short board
    posts make this especially tempting ("난 10만 날려봄", "당첨된 적 없음").
    Keep the rule broad and source-agnostic: if a draft uses first person plus a
    concrete experience/result without explicit user input, it reads conspicuous.
    """

    if has_pattern("unsupported_personal_claim", title, content):
        return True
    combined = _compact(f"{title} {content}")
    first_person = ("난", "나는", "나도", "내가", "저는", "제가")
    experience_tokens = (
        "날려봄",
        "날려봤",
        "잃어봄",
        "당첨된적",
        "해봤",
        "가봤",
        "먹어봄",
        "써봄",
        "본적",
    )
    if any(marker in combined for marker in first_person) and any(
        token in combined for token in experience_tokens
    ):
        return True
    raw_combined = str(f"{title} {content}" or "")
    source_framing = (
        "글 보니까",
        "사진 보니까",
        "원글",
        "원본",
        "저 글",
        "저 사진",
        "게시글",
    )
    if not any(marker in raw_combined for marker in source_framing):
        implied_possession_patterns = (
            r"(?:창고|방|집|서랍|박스|앨범|장롱).{0,14}(?:정리|뒤지|찾|꺼내).{0,14}(?:발견|나오|나왔|있었)",
            r"(?:어릴 ?때|예전에|옛날에).{0,14}(?:모으던|사둔|갖고 있던|가지고 있던)",
            r"(?:오랜만에).{0,12}(?:정리|꺼내|찾).{0,12}(?:카드|박스|구성물|피규어|물건)",
        )
        if any(re.search(pattern, raw_combined) for pattern in implied_possession_patterns):
            return True
    return bool(
        re.search(
            r"(?:난|나는|나도|내가|저는|제가).{0,12}"
            r"(?:만원|만|번|개|회).{0,12}"
            r"(?:날려|잃|당첨)",
            combined,
        )
    )


def structure_failure_reasons(
    title: str,
    content: str = "",
    *,
    style_profile: dict | None = None,
) -> tuple[str, ...]:
    """Policy-driven structural failures that make a draft feel generated."""

    reasons: list[str] = []
    allow_long_laugh = bool(
        isinstance(style_profile, dict) and style_profile.get("allow_long_laugh")
    )
    if has_abstract_moderator_phrasing(title, content):
        reasons.append("진행자식 총평 질문")
    if has_outsider_moderation_phrasing(title, content):
        reasons.append("외부인식 게시판 비평")
    if has_direct_person_callout(title, content):
        reasons.append("특정 유저 호명/저격")
    if has_complaint_judgment(title, content):
        reasons.append("불평/지적형 결론")
    if has_thin_broad_subject(title, content):
        reasons.append("큰 주제어만 든 제목")
    if has_assertive_rumor_question(title, content):
        reasons.append("압박형 의혹 질문")
    if has_attention_grabbing(title, content, allow_long_laugh=allow_long_laugh):
        reasons.append("이목 끄는 호출/확신")
    if has_explanatory_ai_phrasing(title, content):
        reasons.append("AI식 설명문")
    if has_incomplete_title(title):
        reasons.append("판단이 끝나지 않은 제목")
    if has_unsupported_personal_claim(title, content):
        reasons.append("근거 없는 개인 경험")
    return tuple(reasons)


def angle_lanes() -> tuple[tuple[str, str], ...]:
    lanes = []
    for item in _list_at("angle_lanes"):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        instruction = str(item.get("instruction", "")).strip()
        if key and instruction:
            lanes.append((key, instruction))
    return tuple(lanes) or _DEFAULT_ANGLE_LANES


def angle_instruction(key: str) -> str:
    for lane_key, instruction in angle_lanes():
        if lane_key == key:
            return instruction
    return angle_lanes()[0][1]


def speech_shapes() -> tuple[tuple[str, str], ...]:
    shapes = []
    for item in _list_at("speech_shapes"):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        instruction = str(item.get("instruction", "")).strip()
        if key and instruction:
            shapes.append((key, instruction))
    return tuple(shapes) or _DEFAULT_SPEECH_SHAPES


def speech_shape_instruction(key: str) -> str:
    for shape_key, instruction in speech_shapes():
        if shape_key == key:
            return instruction
    return speech_shapes()[0][1]


def question_skeleton_signature(title: str, content: str = "") -> str:
    """Return the policy key for repetitive question scaffolds.

    A batch can legitimately reuse the same topic, but when several drafts
    share the same question frame ("why again", "what changes", "is it that
    easy"), it reads like a generator template. The concrete patterns live in
    ``naturalness_policy.json`` so tuning remains data-driven.
    """

    combined = _compact(f"{title} {content}")
    for item in _list_at("question_skeletons"):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        patterns = item.get("patterns", [])
        if not key or not isinstance(patterns, list):
            continue
        if any(_compact(pattern) and _compact(pattern) in combined for pattern in patterns):
            return key
    return ""


def question_skeleton_label(key: str) -> str:
    """Human-readable label for a question skeleton policy key."""

    for item in _list_at("question_skeletons"):
        if not isinstance(item, dict):
            continue
        if str(item.get("key", "")).strip() == key:
            label = str(item.get("label", "")).strip()
            return label or key
    return key


def reaction_skeleton_signature(title: str, content: str = "") -> str:
    """Return a policy key for repeated non-question reaction scaffolds."""

    combined = _compact(f"{title} {content}")
    for item in _list_at("reaction_skeletons"):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        patterns = item.get("patterns", [])
        if not key or not isinstance(patterns, list):
            continue
        if any(_compact(pattern) and _compact(pattern) in combined for pattern in patterns):
            return key
    return ""


def reaction_skeleton_label(key: str) -> str:
    """Human-readable label for a reaction skeleton policy key."""

    for item in _list_at("reaction_skeletons"):
        if not isinstance(item, dict):
            continue
        if str(item.get("key", "")).strip() == key:
            label = str(item.get("label", "")).strip()
            return label or key
    return key


_QUESTION_ENDINGS = (
    "냐",
    "었나",
    "았나",
    "했나",
    "됐나",
    "되나",
    "있나",
    "없나",
    "바뀌나",
    "나오나",
    "보나",
    "가나",
    "오나",
    "일까",
    "할까",
    "볼까",
    "갈까",
    "올까",
    "걸까",
    "아님",
    "아닌가",
    "맞나",
    "맞냐",
    "건가",
    "거냐",
    "될까",
    "않나",
    "않았나",
    "인가",
    "인지",
    "뭐임",
)

_INTERROGATIVE_MARKERS = (
    "얼마나",
    "어떻게",
    "어디",
    "누가",
    "뭐가",
    "뭐를",
    "뭘",
    "몇",
)

_INTERROGATIVE_OMITTED_ENDINGS = (
    "남음",
    "남나",
    "나옴",
    "됨",
    "되냐",
    "걸림",
    "듦",
    "들어감",
    "필요함",
    "받음",
    "씀",
    "팜",
)


def _policy_question_endings() -> tuple[str, ...]:
    values = tuple(
        str(item).strip()
        for item in _list_at("question_endings")
        if str(item).strip()
    )
    return values or _QUESTION_ENDINGS


def _question_core(text: str) -> tuple[str, str]:
    value = str(text or "").rstrip()
    match = re.search(r"([ㅋㅎ]+)$", value)
    tail = match.group(1) if match else ""
    core = value[: -len(tail)].rstrip() if tail else value
    return core, tail


def looks_like_question(text: str) -> bool:
    """Detect colloquial questions even when the model omitted ``?``."""

    core, _tail = _question_core(text)
    if not core:
        return False
    if core.endswith("?"):
        return True
    compact_core = _compact(core)
    if any(marker in compact_core for marker in _INTERROGATIVE_MARKERS) and any(
        compact_core.endswith(ending) for ending in _INTERROGATIVE_OMITTED_ENDINGS
    ):
        return True
    return any(
        compact_core.endswith(_compact(ending))
        for ending in _policy_question_endings()
        if _compact(ending)
    )


def is_direct_question(title: str, content: str = "") -> bool:
    """Return True when a draft's main move is a direct question.

    Korean board titles often omit ``?`` while still ending as a question.
    Counting those endings lets the batch controller keep questions occasional
    instead of letting every persona collapse into the same prompt-shaped post.
    """

    return looks_like_question(title)


def direct_question_cap(batch_size: int) -> int:
    """Keep direct questions rare in review batches.

    Question-heavy batches read like a prompt template. Keep one question as
    the default ceiling; very large batches may use a second one.
    """

    size = max(0, int(batch_size))
    if size <= 15:
        return 1
    return 2


def ensure_question_punctuation(text: str) -> str:
    """Add a question mark when a colloquial question clearly lacks one.

    Trailing laughter stays after the mark: ``맞냐ㅋㅋ`` -> ``맞냐?ㅋㅋ``.
    Declarative endings such as ``있음`` and ``맞음`` are intentionally not
    changed.
    """

    value = str(text or "").rstrip()
    if not value:
        return value
    core, tail = _question_core(value)
    if core.endswith(("?", "!", ".", "…")):
        return value
    if looks_like_question(value):
        return f"{core}?{tail}"
    return value


def ensure_question_punctuation_in_lines(text: str) -> str:
    """Apply question punctuation normalization to each generated text line.

    Titles already pass through :func:`ensure_question_punctuation`, but body
    and comment drafts often use the same board-style endings on separate
    lines. Normalizing line-by-line catches endings such as ``아님`` without
    rewriting the surrounding wording.
    """

    value = str(text or "").rstrip()
    if not value:
        return value
    return "\n".join(ensure_question_punctuation(line) for line in value.splitlines())


def slot_sequence() -> tuple[str, ...]:
    values = tuple(str(item) for item in _list_at("slot_sequence") if str(item).strip())
    return values or ("A", "B", "A", "C", "A", "B", "C", "A", "B", "C")


def persona_angle_preferences() -> dict[str, tuple[str, ...]]:
    data = load_policy().get("persona_angle_overrides", {})
    if not isinstance(data, dict):
        return {}
    preferences: dict[str, tuple[str, ...]] = {}
    for key, value in data.items():
        if isinstance(value, list):
            angles = tuple(str(item).strip() for item in value if str(item).strip())
        else:
            angles = (str(value).strip(),) if str(value).strip() else ()
        if angles:
            preferences[str(key)] = angles
    return preferences


def persona_angle_overrides() -> dict[str, str]:
    """Backward-compatible first-choice view of persona angle preferences."""

    return {
        key: values[0]
        for key, values in persona_angle_preferences().items()
        if values
    }


def phase_instruction(progress: float) -> str:
    flow = load_policy().get("batch_flow", {})
    if not isinstance(flow, dict):
        return ""
    early = flow.get("early", {})
    middle = flow.get("middle", {})
    late = flow.get("late", {})
    early_until = float(early.get("until", 0.38)) if isinstance(early, dict) else 0.38
    middle_until = float(middle.get("until", 0.72)) if isinstance(middle, dict) else 0.72
    if progress < early_until and isinstance(early, dict):
        return str(early.get("instruction", "")).strip()
    if progress < middle_until and isinstance(middle, dict):
        return str(middle.get("instruction", "")).strip()
    if isinstance(late, dict):
        return str(late.get("instruction", "")).strip()
    return ""


def bullet_block(title: str, lines: Iterable[str]) -> str:
    clean = [str(line).strip() for line in lines if str(line).strip()]
    if not clean:
        return ""
    body = "\n".join(f"- {line}" for line in clean)
    return f"[{title}]\n{body}\n"


def generation_policy_block() -> str:
    return bullet_block("자연스러움 정책", _list_at("generation_rules"))


def final_check_block() -> str:
    return bullet_block("자연스러움 FINAL CHECK", _list_at("final_checks"))


def judge_policy_text() -> str:
    violation = str(load_policy().get("judge_violation", "")).strip()
    allowance = str(load_policy().get("judge_allowance", "")).strip()
    parts = []
    if violation:
        parts.append(f"[자연스러움 위반]\n{violation}")
    if allowance:
        parts.append(f"[자연스러움 허용]\n{allowance}")
    return "\n".join(parts)


def persona_rule(persona_key: str) -> str:
    rules = load_policy().get("persona_rules", {})
    if not isinstance(rules, dict):
        return ""
    return str(rules.get(persona_key, "")).strip()
