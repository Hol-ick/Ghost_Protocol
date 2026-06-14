"""Persona lineup policy for batch generation.

The Streamlit app used to own this logic directly. Keeping it here makes the
generation mix testable and keeps UI code focused on UI state.
"""

from __future__ import annotations

import math
import random

from ghost_protocol import cycle_memory as cycle_memory
from ghost_protocol import prompt_manager as pm


PERSONA_POOL: list[dict] = pm.load_json("personas.json")
PERSONA_BY_KEY: dict[str, dict] = {p["key"]: p for p in PERSONA_POOL}

# Active roles describe a useful contribution to the thread. Legacy roles that
# mainly ask for context, summarize the board, or announce activity remain in
# the prompt assets for old saved sessions, but are not sampled for new batches.
ACTIVE_PERSONA_KEYS: frozenset[str] = frozenset(
    {
        "scene_noticer",
        "detail_extender",
        "light_joker",
        "experience_linker",
        "possibility_mapper",
        "neutral",
        "analytical",
        "solution_proposer",
        "hopium",
        "topic_diverger",
    }
)
ACTIVE_PERSONA_POOL: list[dict] = [
    p for p in PERSONA_POOL if p["key"] in ACTIVE_PERSONA_KEYS
]

MUTANT_KEYS: frozenset[str] = frozenset(
    {"solution_proposer", "hopium", "possibility_mapper"}
)
PERSONA_HOT_KEYS: frozenset[str] = frozenset()
ATTENTION_HEAVY_KEYS: frozenset[str] = frozenset(
    {"aggressive", "aggro", "paranoid", "rally_crier"}
)
QUESTION_HEAVY_KEYS: frozenset[str] = frozenset()
PERSONA_NEUTRAL_KEYS: frozenset[str] = frozenset(
    {"neutral", "analytical", "scene_noticer", "detail_extender", "experience_linker"}
)
PERSONA_ANCHOR_SEQUENCE: tuple[str, ...] = (
    "scene_noticer",
    "detail_extender",
    "light_joker",
    "experience_linker",
    "possibility_mapper",
    "analytical",
    "solution_proposer",
    "topic_diverger",
    "neutral",
    "hopium",
)

MUTANT_POOL: list[dict] = [p for p in ACTIVE_PERSONA_POOL if p["key"] in MUTANT_KEYS]
HOT_POOL: list[dict] = [p for p in ACTIVE_PERSONA_POOL if p["key"] in PERSONA_HOT_KEYS]
NEUTRAL_POOL: list[dict] = [
    p for p in ACTIVE_PERSONA_POOL if p["key"] in PERSONA_NEUTRAL_KEYS
]
WARM_POOL: list[dict] = [
    p
    for p in ACTIVE_PERSONA_POOL
    if p["key"] not in PERSONA_HOT_KEYS
    and p["key"] not in PERSONA_NEUTRAL_KEYS
    and p["key"] not in MUTANT_KEYS
]
PARTICIPANT_POOL: list[dict] = [
    p
    for p in ACTIVE_PERSONA_POOL
    if p["key"] not in ATTENTION_HEAVY_KEYS
    and p["key"] not in QUESTION_HEAVY_KEYS
]

LATE_NIGHT: frozenset[int] = frozenset({23, 0, 1, 2, 3})
RUSH_HOUR: frozenset[int] = frozenset({7, 8, 9})
LUNCH: frozenset[int] = frozenset({12, 13})
EVENING: frozenset[int] = frozenset({20, 21, 22})


def fix_consecutive_same(lineup: list[dict]) -> list[dict]:
    """Move items around so the same persona key does not repeat back to back."""
    result = list(lineup)
    for i in range(1, len(result)):
        if result[i]["key"] == result[i - 1]["key"]:
            swapped = False
            for j in range(i + 1, len(result)):
                if result[j]["key"] != result[i]["key"]:
                    result[i], result[j] = result[j], result[i]
                    swapped = True
                    break
            if not swapped:
                for j in range(i - 2, -1, -1):
                    if result[j]["key"] != result[i]["key"]:
                        result[i], result[j] = result[j], result[i]
                        break
    return result


def fix_consecutive_hot(lineup: list[dict]) -> list[dict]:
    """Avoid three HOT-tier personas in a row where the pool allows it."""
    result = list(lineup)
    for i in range(2, len(result)):
        if (
            result[i]["key"] in PERSONA_HOT_KEYS
            and result[i - 1]["key"] in PERSONA_HOT_KEYS
            and result[i - 2]["key"] in PERSONA_HOT_KEYS
        ):
            swapped = False
            for j in range(i + 1, len(result)):
                if result[j]["key"] not in PERSONA_HOT_KEYS:
                    result[i], result[j] = result[j], result[i]
                    swapped = True
                    break
            if not swapped:
                for j in range(i - 3, -1, -1):
                    if result[j]["key"] not in PERSONA_HOT_KEYS:
                        result[i], result[j] = result[j], result[i]
                        break
    return result


def cap_question_heavy(lineup: list[dict], max_count: int) -> list[dict]:
    """Keep scene-check roles occasional instead of making them the batch voice."""
    result = list(lineup)
    seen = 0
    counts: dict[str, int] = {}
    for item in result:
        counts[item["key"]] = counts.get(item["key"], 0) + 1

    for index, item in enumerate(result):
        if item["key"] not in QUESTION_HEAVY_KEYS:
            continue
        seen += 1
        if seen <= max_count:
            continue
        replacements = [
            candidate
            for candidate in PARTICIPANT_POOL
            if candidate["key"] != item["key"]
            and counts.get(candidate["key"], 0) < 2
        ] or PARTICIPANT_POOL
        replacement = random.choice(replacements)
        counts[item["key"]] -= 1
        counts[replacement["key"]] = counts.get(replacement["key"], 0) + 1
        result[index] = replacement
    return result


def cap_persona_repetition(lineup: list[dict], max_per_key: int = 2) -> list[dict]:
    """Replace excess repeats so one voice cannot dominate a large batch."""

    result: list[dict] = []
    counts: dict[str, int] = {}
    for item in lineup:
        key = item["key"]
        if counts.get(key, 0) < max_per_key:
            chosen = item
        else:
            candidates = [
                candidate
                for candidate in ACTIVE_PERSONA_POOL
                if counts.get(candidate["key"], 0) < max_per_key
                and (not result or candidate["key"] != result[-1]["key"])
            ]
            chosen = min(
                candidates,
                key=lambda candidate: counts.get(candidate["key"], 0),
                default=item,
            )
        counts[chosen["key"]] = counts.get(chosen["key"], 0) + 1
        result.append(chosen)
    return result


def sample_capped(pool: list[dict], n: int, max_per_key: int = 2) -> list[dict]:
    """Sample n personas while keeping one key from dominating the batch."""
    if n <= 0 or not pool:
        return []
    result: list[dict] = []
    counts: dict[str, int] = {}
    for _ in range(n):
        available = [p for p in pool if counts.get(p["key"], 0) < max_per_key]
        chosen = random.choice(available if available else pool)
        result.append(chosen)
        counts[chosen["key"]] = counts.get(chosen["key"], 0) + 1
    return result


def _anchor_personas(wave_count: int) -> list[dict]:
    """Guarantee a baseline mix of community roles before random flavor."""

    if wave_count <= 0:
        return []
    if wave_count < 4:
        anchor_count = min(2, wave_count)
    elif wave_count < 8:
        anchor_count = min(4, wave_count)
    else:
        anchor_count = min(6, wave_count)
    return [
        PERSONA_BY_KEY[key]
        for key in PERSONA_ANCHOR_SEQUENCE[:anchor_count]
        if key in PERSONA_BY_KEY
    ]


def _unused_personas(existing: list[dict], *, exclude_attention_heavy: bool = True) -> list[dict]:
    """Return active personas not already present, preserving anchor order first."""

    used = {item["key"] for item in existing}
    pool = [
        PERSONA_BY_KEY[key]
        for key in PERSONA_ANCHOR_SEQUENCE
        if key in PERSONA_BY_KEY and key not in used
    ]
    pool.extend(
        persona
        for persona in ACTIVE_PERSONA_POOL
        if persona["key"] not in used
        and persona["key"] not in {item["key"] for item in pool}
    )
    if exclude_attention_heavy:
        filtered = [
            persona for persona in pool if persona["key"] not in ATTENTION_HEAVY_KEYS
        ]
        return filtered or pool
    return pool


def prefer_unique_when_possible(lineup: list[dict]) -> list[dict]:
    """Replace duplicate personas while the active pool can cover the batch.

    Small batches are where repeated voices are most visible. If we have enough
    active personas to fill the requested size, keep each persona unique before
    falling back to the normal large-batch repetition cap.
    """

    if len(lineup) > len(ACTIVE_PERSONA_POOL):
        return list(lineup)

    counts: dict[str, int] = {}
    for item in lineup:
        counts[item["key"]] = counts.get(item["key"], 0) + 1

    missing = [
        persona
        for persona in _unused_personas([], exclude_attention_heavy=True)
        if counts.get(persona["key"], 0) == 0
    ]
    if not missing:
        return list(lineup)

    result: list[dict] = []
    seen: set[str] = set()
    for item in lineup:
        key = item["key"]
        if key not in seen:
            result.append(item)
            seen.add(key)
            continue
        replacement = missing.pop(0) if missing else item
        result.append(replacement)
        seen.add(replacement["key"])
    return result


def _weighted_warm_pool(hour: int) -> list[dict]:
    weighted = list(WARM_POOL)
    if hour in LATE_NIGHT:
        weighted += [p for p in WARM_POOL if p["key"] == "monologue"]
    elif hour in RUSH_HOUR:
        weighted += [
            p for p in WARM_POOL if p["key"] in ("scene_noticer", "neutral")
        ]
    elif hour in LUNCH:
        weighted += [
            p for p in WARM_POOL if p["key"] in ("humblebragger", "monologue")
        ]
    elif hour in EVENING:
        weighted += [
            p
            for p in WARM_POOL
            if p["key"] in ("light_joker", "topic_diverger")
        ]
    return weighted


def build_balanced_lineup(
    wave_count: int,
    *,
    sentiment_score: int = 0,
    hour: int = -1,
) -> list[dict]:
    """Build a persona lineup with bounded heat and enough tonal variety."""
    if wave_count <= 0:
        return []

    is_drifted = sentiment_score <= cycle_memory.DRIFT_THRESHOLD
    hot_ratio = 0.08 if is_drifted else 0.18

    if hour in LATE_NIGHT and not is_drifted:
        hot_ratio = min(0.22, hot_ratio + 0.04)

    max_hot = max(0, int(wave_count * hot_ratio))
    min_neutral = max(1, math.ceil(wave_count * 0.10))

    if is_drifted:
        mutant_count = min(2, wave_count, len(MUTANT_POOL))
    else:
        mutant_count = random.randint(1, min(2, wave_count, len(MUTANT_POOL)))
    remaining = wave_count - mutant_count

    hot_count = (
        random.randint(0, min(max_hot, remaining))
        if remaining > 0 and HOT_POOL
        else 0
    )
    remaining -= hot_count

    neutral_count = min(min_neutral + random.randint(0, 2), remaining)
    neutral_count = max(0, neutral_count)
    remaining -= neutral_count

    low_attention_warm = [
        p for p in _weighted_warm_pool(hour) if p["key"] not in ATTENTION_HEAVY_KEYS
    ]
    sampled_slots = (
        random.sample(MUTANT_POOL, mutant_count)
        + sample_capped(HOT_POOL, hot_count)
        + sample_capped(NEUTRAL_POOL, neutral_count)
        + sample_capped(low_attention_warm or _weighted_warm_pool(hour), max(0, remaining))
    )
    anchors = _anchor_personas(wave_count)
    anchor_keys = {p["key"] for p in anchors}
    slots = anchors + [p for p in sampled_slots if p["key"] not in anchor_keys]
    while len(slots) < wave_count:
        unused = _unused_personas(slots)
        if unused:
            needed = wave_count - len(slots)
            slots.extend(unused[:needed])
            continue
        fallback_pool = [
            p for p in ACTIVE_PERSONA_POOL if p["key"] not in ATTENTION_HEAVY_KEYS
        ] or ACTIVE_PERSONA_POOL
        slots.extend(sample_capped(fallback_pool, wave_count - len(slots)))
    slots = slots[:wave_count]
    slots = prefer_unique_when_possible(slots)
    slots = cap_question_heavy(slots, max_count=max(1, math.ceil(wave_count * 0.10)))
    random.shuffle(slots)
    slots = cap_persona_repetition(slots, max_per_key=2)
    slots = fix_consecutive_same(slots)
    return fix_consecutive_hot(slots)
