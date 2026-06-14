"""Infer a gallery's durable subject and reserve grounded purpose slots."""

from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Iterable

from ghost_protocol import prompt_manager as pm


@lru_cache(maxsize=1)
def load_profiles() -> dict[str, dict]:
    data = pm.load_json("gallery_purposes.json")
    if not isinstance(data, dict):
        return {}
    topics = data.get("topics")
    if isinstance(topics, list):
        profiles = {}
        for value in topics:
            if not isinstance(value, dict):
                continue
            key = str(value.get("key") or "").strip()
            if key:
                profiles[key] = value
        return profiles
    # Backward compatibility for saved installations using the v1 exact map.
    return {
        str(key): value
        for key, value in data.items()
        if not str(key).startswith("_") and isinstance(value, dict)
    }


def _normalized_tokens(value: object) -> set[str]:
    return set(re.findall(r"[0-9a-z가-힣]+", str(value or "").casefold()))


def _known_gallery_name(gallery_id: str) -> str:
    """Return a configured display name when the style DB recognizes the id."""

    contexts = pm.load_json("gallery_contexts.json")
    if not isinstance(contexts, dict):
        return ""
    gallery_key = str(gallery_id or "").strip().casefold()
    best_name = ""
    best_score = 0
    for key, value in contexts.items():
        if str(key).startswith("_") or not isinstance(value, dict):
            continue
        context_key = str(key).strip().casefold()
        if context_key == "default":
            continue
        score = 0
        if gallery_key == context_key:
            score = 4
        elif context_key and context_key in gallery_key:
            score = 2
        if score > best_score:
            best_score = score
            best_name = str(value.get("gallery_name") or "").strip()
    return best_name


def _match_score(profile: dict, gallery_id: str, gallery_name: str) -> int:
    id_value = str(gallery_id or "").casefold()
    name_value = str(gallery_name or "").casefold()
    id_tokens = _normalized_tokens(id_value)
    name_tokens = _normalized_tokens(name_value)
    score = 0
    for token in profile.get("id_tokens", []):
        normalized = str(token or "").strip().casefold()
        if not normalized:
            continue
        if normalized in id_tokens:
            score += 6
        elif normalized in id_value:
            score += 3
    for token in profile.get("name_tokens", []):
        normalized = str(token or "").strip().casefold()
        if not normalized:
            continue
        if normalized in name_tokens:
            score += 6
        elif normalized in name_value:
            score += 3
    return score


def get_profile(gallery_id: str, gallery_name: str = "") -> dict:
    """Infer a subject profile from ID/name tokens instead of an exact ID map."""

    gallery_id = str(gallery_id or "").strip()
    if not gallery_id:
        return {}
    resolved_name = str(gallery_name or "").strip() or _known_gallery_name(gallery_id)
    matches = [
        (_match_score(profile, gallery_id, resolved_name), key, profile)
        for key, profile in load_profiles().items()
    ]
    score, key, profile = max(matches, default=(0, "", {}), key=lambda item: item[0])
    if score <= 0:
        return {}
    result = dict(profile)
    result["inferred_key"] = key
    result["inferred_from"] = resolved_name or gallery_id
    return result


def purpose_wave_indices(total_count: int) -> tuple[int, ...]:
    """Return low-key gallery-purpose slots scaled to the batch size."""

    total = max(1, int(total_count or 1))
    if total < 12:
        return (max(1, (total + 1) // 2),)
    return (
        max(1, round(total * 0.40)),
        min(total, max(2, round(total * 0.85))),
    )


def purpose_wave_index(total_count: int) -> int:
    """Return the first purpose slot for compatibility with older callers."""

    return purpose_wave_indices(total_count)[0]


def is_purpose_wave(gallery_id: str, wave_index: int, total_count: int) -> bool:
    return (
        bool(get_profile(gallery_id))
        and int(wave_index) in purpose_wave_indices(total_count)
    )


def keyword_list(profile: dict) -> tuple[str, ...]:
    values = profile.get("keywords", [])
    if not isinstance(values, list):
        return ()
    return tuple(str(value).strip() for value in values if str(value).strip())


def fallback_angles(profile: dict) -> tuple[str, ...]:
    values = profile.get("fallback_angles", [])
    if not isinstance(values, list):
        return ()
    return tuple(str(value).strip() for value in values if str(value).strip())


def target_share(profile: dict) -> float:
    """Return the desired share of gallery-purpose drafts in one batch."""

    try:
        value = float(profile.get("target_share", 0.30))
    except (TypeError, ValueError):
        value = 0.30
    return min(0.60, max(0.10, value))


def target_count(gallery_id: str, total_count: int) -> int:
    profile = get_profile(gallery_id)
    if not profile:
        return 0
    total = max(1, int(total_count or 1))
    return min(total, max(1, math.ceil(total * target_share(profile))))


def identity_metadata(gallery_id: str, gallery_name: str = "") -> dict[str, object]:
    """Return the durable board identity inferred from configured ID/name tokens."""

    profile = get_profile(gallery_id, gallery_name)
    if not profile:
        return {}
    return {
        "gallery_id": str(gallery_id or "").strip(),
        "gallery_name": str(profile.get("gallery_name") or "").strip(),
        "topic_label": str(profile.get("topic_label") or "").strip(),
        "target_share": target_share(profile),
        "guidance": str(profile.get("guidance") or "").strip(),
    }


def analysis_context(gallery_id: str, gallery_name: str = "") -> str:
    """Build the durable identity block used by analysis and rehearsal."""

    identity = identity_metadata(gallery_id, gallery_name)
    if not identity:
        return "(등록된 기본 분야 없음: 현재 수집 데이터만 분석)"
    share_percent = max(1, round(float(identity["target_share"]) * 100))
    return "\n".join(
        [
            "[게시판 지속 정체성]",
            f"- 갤러리 ID: {identity['gallery_id']}",
            f"- ID/등록 이름에서 추론한 기본 분야: {identity['topic_label']}",
            "- 이 정보는 현재 유행의 증거가 아니라 게시판의 지속적인 기본축이다.",
            "- 브리핑에서는 기본축과 현재 수집 화제를 분리해서 설명한다.",
            f"- 후속 배치의 약 {share_percent}%는 기본 분야의 상시 소재에 배정한다.",
            "- 기본 분야 글은 갤러리 이름이나 화제 전환을 언급하지 않고 소재에 바로 참여한다.",
        ]
    )


def briefing_prefix(gallery_id: str, gallery_name: str = "") -> str:
    identity = identity_metadata(gallery_id, gallery_name)
    if not identity:
        return ""
    return (
        f"ID 기반 기본축은 {identity['topic_label']}입니다. 현재 수집분에서는"
    )


def strip_identity_echo(text: str, gallery_id: str, gallery_name: str = "") -> str:
    """Remove model-echoed board identity sentences before adding our prefix.

    Trend analysis receives the inferred board identity as context, but the
    UI should show it once in a deterministic prefix. Without this cleanup,
    rehearsal cycles repeatedly feed phrases like "universe 갤러리의 기본 분야는..."
    back into the next cycle and amplify them.
    """

    cleaned = str(text or "").strip()
    identity = identity_metadata(gallery_id, gallery_name)
    if not cleaned or not identity:
        return cleaned

    gallery_tokens = [
        str(identity.get("gallery_id") or "").strip(),
        str(identity.get("gallery_name") or "").strip(),
        str(gallery_name or "").strip(),
    ]
    label = str(identity.get("topic_label") or "").strip()
    identity_terms = [token.casefold() for token in gallery_tokens if token]
    if label:
        identity_terms.extend(part.casefold() for part in re.split(r"[·/\s]+", label) if part)

    def _looks_like_identity_echo(sentence: str) -> bool:
        lowered = sentence.casefold()
        has_identity = any(term and term in lowered for term in identity_terms)
        has_meta = any(
            marker in sentence
            for marker in (
                "기본 분야",
                "기본축",
                "ID",
                "갤러리",
                "다루는 곳",
                "추론",
                "본래 분야",
            )
        )
        return has_identity and has_meta

    # Drop up to three leading identity/meta sentences. Rehearsal summaries may
    # start with both our deterministic prefix and the model's echoed board
    # identity, so keep this cleanup slightly more tolerant than UI rendering.
    for _ in range(3):
        match = re.match(r"^([^.!?\n。]{1,260}[.!?。])\s*(.*)$", cleaned, re.DOTALL)
        if not match:
            break
        first, rest = match.group(1), match.group(2)
        if not _looks_like_identity_echo(first):
            break
        cleaned = rest.strip()

    # Remove transitional boilerplate that duplicates our deterministic prefix.
    cleaned = re.sub(
        r"^(?:ID\s*기반\s*기본축은\s*[^.!?\n。]{1,120}[.!?。]\s*)+",
        "",
        cleaned,
    ).strip()
    cleaned = re.sub(
        r"^(?:게시판\s*ID\s*`?[^`\s]+`?에서\s*추론한\s*기본\s*분야는\s*[^.!?\n。]{1,120}[.!?。]\s*)+",
        "",
        cleaned,
    ).strip()
    cleaned = re.sub(r"^(?:이\s*기본축과\s*별개로,\s*)", "", cleaned).strip()
    cleaned = re.sub(r"^(?:현재\s*수집분(?:에)?서는\s*)+", "", cleaned).strip()
    cleaned = re.sub(r"^(?:현재\s*수집\s*데이터(?:에)?서는\s*)+", "", cleaned).strip()
    cleaned = re.sub(r"(현재\s*수집분(?:에)?서는\s*){2,}", "현재 수집분에서는 ", cleaned).strip()
    cleaned = re.sub(
        r"\s*ID/이름\s*토큰으로\s*추론한\s*기본\s*분야\([^)]*\)\s*소재를\s*[^.!?\n。]{1,180}[.!?。]?",
        "",
        cleaned,
    ).strip()
    return cleaned


def generation_instruction(gallery_id: str, gallery_name: str = "") -> str:
    identity = identity_metadata(gallery_id, gallery_name)
    if not identity:
        return ""
    share_percent = max(1, round(float(identity["target_share"]) * 100))
    return (
        f"등록된 상시 분야({identity['topic_label']}) 소재는 배치의 약 {share_percent}%만 낮게 유지한다. "
        "현재 유행인 척하거나 본래 주제로 돌아가자고 말하지 말고, "
        "상시 관찰·구체 대상·작은 사실 중 하나로 대화에 바로 참여한다. "
        "기본 분야 슬롯은 불평이나 주제 전환 선언이 아니라 대상 자체의 장면으로 시작한다."
    )


def rehearsal_context(gallery_id: str, gallery_name: str = "") -> str:
    """Build a stronger, rehearsal-only anchor for durable board identity."""

    identity = identity_metadata(gallery_id, gallery_name)
    if not identity:
        return ""
    profile = get_profile(gallery_id, gallery_name)
    fallbacks = fallback_angles(profile)
    share_percent = max(1, round(float(identity["target_share"]) * 100))
    lines = [
        "[리허설 기본축 앵커]",
        f"- 등록된 상시 분야: {identity['topic_label']}",
        f"- 다음 사이클에서도 약 {share_percent}%만 낮게 유지한다. 10개 기준 1~2개면 충분하다.",
        "- 갤러리 이름, ID, '본래 주제'라는 말은 원고에 쓰지 않는다.",
        "- 기본축 슬롯은 불평·지적·뜻 질문이 아니라 구체 대상/수치/관측 장면으로 바로 시작한다.",
    ]
    if fallbacks:
        lines.append("- 원본에 기본축 소재가 적으면 아래 상시 각도 중 하나만 조용히 쓴다:")
        lines.extend(f"  - {angle}" for angle in fallbacks[:4])
    return "\n".join(lines)


def _keyword_matches(keyword: str, combined: str, tokens: set[str]) -> bool:
    normalized = str(keyword or "").strip().casefold()
    if not normalized:
        return False
    if len(normalized) <= 1:
        return normalized in tokens
    return normalized in combined


def text_matches(gallery_id: str, title: str, content: str = "") -> bool:
    profile = get_profile(gallery_id)
    combined = f"{title} {content}".casefold()
    tokens = set(re.findall(r"[0-9a-z가-힣]+", combined))
    return any(
        _keyword_matches(keyword, combined, tokens)
        for keyword in keyword_list(profile)
    )


def source_examples(profile: dict, posts: Iterable[dict], *, limit: int = 4) -> list[str]:
    """Return purpose-matching source snippets, preserving source grounding."""

    keywords = keyword_list(profile)
    if not keywords:
        return []
    examples: list[str] = []
    for post in posts or []:
        if not isinstance(post, dict):
            continue
        title = str(post.get("title") or post.get("source_title") or "").strip()
        content = str(post.get("content") or post.get("body") or "").strip()
        combined = f"{title} {content}".casefold()
        tokens = set(re.findall(r"[0-9a-z가-힣]+", combined))
        if not title or not any(
            _keyword_matches(keyword, combined, tokens)
            for keyword in keywords
        ):
            continue
        snippet = title if not content else f"{title} — {content[:90]}"
        examples.append(snippet)
        if len(examples) >= limit:
            break
    return examples


def purpose_candidates(
    gallery_id: str,
    source_posts: Iterable[dict] = (),
    *,
    allow_fallback: bool = True,
) -> tuple[str, ...]:
    """Return distinct grounded/fallback purpose angles for plan rotation."""

    profile = get_profile(gallery_id)
    if not profile:
        return ()
    examples = source_examples(profile, source_posts, limit=8)
    values = examples or (list(fallback_angles(profile)) if allow_fallback else [])
    return tuple(dict.fromkeys(value for value in values if value))


def guidance_block(
    gallery_id: str,
    source_posts: Iterable[dict] = (),
    *,
    focus: str = "",
) -> str:
    profile = get_profile(gallery_id)
    if not profile:
        return ""
    label = str(profile.get("topic_label") or "본래 주제").strip()
    guidance = str(profile.get("guidance") or "").strip()
    parts = [
        "[G: 갤러리 본래 주제]",
        f"- 분야: {label}",
        f"- 지시: {guidance}",
        "- ID는 분야 선택에만 사용한다. 게시글 소재는 실제 원본 또는 상시 각도에서 고른다.",
        "- 본래 주제를 요구하거나 갤러리 이름을 언급하지 말고, 그 소재의 대화에 바로 참여한다.",
        "- 제목과 본문에는 이번 초점의 구체 대상·현상·장면 중 하나가 반드시 드러나야 한다.",
        "- 불평, 게시판 평가, 뜻 질문으로 시작하지 않는다. 이미 이 분야를 보던 사람처럼 한 조각을 보탠다.",
    ]
    selected_focus = str(focus or "").strip()
    if selected_focus:
        parts.append(f"- 이번 초점: {selected_focus}")
    else:
        examples = source_examples(profile, source_posts)
        if examples:
            parts.append(
                "- 원본 예시:\n"
                + "\n".join(f"  - {example}" for example in examples)
            )
        else:
            fallbacks = fallback_angles(profile)
            if fallbacks:
                parts.append(
                    "- 현재 원본에 본래 주제가 없으면 새 사건을 꾸며내지 말고 "
                    "다음 상시 각도 중 하나만 쓴다:\n"
                    + "\n".join(f"  - {angle}" for angle in fallbacks)
                )
    return "\n".join(parts)
