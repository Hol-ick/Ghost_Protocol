"""Batch-level conversation planning for draft generation.

Seed slots and personas are useful, but they can still collapse into the same
noun plus the same reaction.  This module adds a deterministic conversation
arc: which kind of topic each wave should use, which stance it should take, and
which recently accepted titles it should avoid echoing.

The planner is intentionally gallery-agnostic.  It may consume the existing
gallery-purpose inference layer, but it does not hardcode individual gallery
IDs or subjects.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable

from ghost_protocol.domain import draft_guidance
from ghost_protocol.domain import gallery_purpose


_STOPWORDS = {
    "this",
    "that",
    "with",
    "from",
    "about",
    "topic",
    "post",
    "board",
    "gallery",
    "current",
    "source",
    "\uadf8\ub0e5",  # just
    "\uadfc\ub370",  # but
    "\uc9c4\uc9dc",  # really
    "\uc774\uac70",  # this thing
    "\uc800\uac70",  # that thing
    "\uadf8\uac70",  # it
    "\ubb50\uac00",  # what
    "\uac8c\uc2dc\ud310",  # board
    "\uac24\ub7ec\ub9ac",  # gallery
    "\ubd84\uc704\uae30",  # mood
    "\uc8fc\uc81c",  # topic
    "\uad00\ub828",  # related
    "\uc774\ub984",  # name
    "\ubc18\uc751",  # reaction
    "\uc0ac\ub78c",  # person
    "\uae00",  # post
}


_STANCE_LANES: tuple[tuple[str, str], ...] = (
    (
        "add_detail",
        "Add one concrete detail or small number. Do not conclude that the whole topic is bad.",
    ),
    (
        "soft_counter",
        "Push back lightly against the previous angle, but avoid scolding or moralizing.",
    ),
    (
        "small_consequence",
        "Mention one small practical consequence, not a grand social diagnosis.",
    ),
    (
        "scene_fragment",
        "Start from a visible scene, object, number, phrase, or tiny moment.",
    ),
    (
        "low_joke",
        "Use a low-key aside or dry joke. Keep it as participation, not commentary on the board.",
    ),
    (
        "curious_followup",
        "Leave a small follow-up thought. Use a question mark only if the sentence truly asks.",
    ),
    (
        "personal_scale",
        "Bring the issue down to time, cost, hassle, convenience, or everyday scale.",
    ),
)


_ROLE_RULES: dict[str, str] = {
    "main_thread": (
        "Use a currently visible hot topic, but approach it through a narrow object, number, "
        "scene, or consequence. Do not repeat the broad briefing label."
    ),
    "side_thread": (
        "Use a smaller side topic from real source posts/comments. It should feel like a quiet "
        "new post, not like an announcement that the topic is changing."
    ),
    "gallery_axis": (
        "Use the durable gallery subject only as one normal post in the flow. Do not mention "
        "the gallery name, original purpose, or that you are returning to the subject."
    ),
    "casual_detail": (
        "Use a small everyday or throwaway detail from the source set. Keep it low-stakes and "
        "avoid board-wide critique."
    ),
}


def _clean(value: object, *, limit: int = 220) -> str:
    return " ".join(str(value or "").split())[:limit]


def _tokens(value: object) -> frozenset[str]:
    found: list[str] = []
    for token in re.findall("[0-9A-Za-z_\uac00-\ud7a3]{2,}", str(value or "").casefold()):
        if token.isdigit() or token in _STOPWORDS:
            continue
        found.append(token)
    return frozenset(found)


def _title_of(post: dict) -> str:
    return _clean(post.get("title") or post.get("source_title"), limit=180)


def _body_of(post: dict) -> str:
    return _clean(post.get("content") or post.get("body"), limit=240)


def _unique_topic_items(items: Iterable[dict]) -> list[dict]:
    unique: list[dict] = []
    seen: list[frozenset[str]] = []
    for item in items:
        text = f"{item.get('label', '')} {item.get('source_title', '')}"
        family = _tokens(text)
        if not family:
            continue
        if any(draft_guidance.same_topic_family(family, existing) for existing in seen):
            continue
        clone = dict(item)
        clone["family_tokens"] = tuple(sorted(family))
        unique.append(clone)
        seen.append(family)
    return unique


def _source_items(source_posts: Iterable[dict], *, limit: int = 8) -> list[dict]:
    items: list[dict] = []
    for post in source_posts or []:
        if not isinstance(post, dict):
            continue
        title = _title_of(post)
        body = _body_of(post)
        if not title:
            continue
        comments = post.get("comments")
        if comments is None:
            comments = post.get("existing_comments")
        comment_text = ""
        if isinstance(comments, list) and comments:
            comment_text = _clean(comments[0], limit=120)
        label = title if len(title) <= 60 else title[:57] + "..."
        items.append(
            {
                "role": "side_thread",
                "label": label,
                "source_title": title,
                "source_body": body,
                "source_comment": comment_text,
            }
        )
        if len(items) >= limit:
            break
    return _unique_topic_items(items)


def _seed_items(topic: object) -> list[dict]:
    slots = draft_guidance.extract_seed_slots(topic)
    return _unique_topic_items(
        {
            "role": "main_thread",
            "slot": label,
            "label": text,
            "source_title": text,
        }
        for label, text in slots.items()
        if text
    )


def _gallery_items(
    gallery_id: str,
    source_posts: Iterable[dict],
    *,
    enabled: bool,
) -> list[dict]:
    if not enabled:
        return []
    candidates = gallery_purpose.purpose_candidates(
        gallery_id,
        source_posts,
        allow_fallback=not bool(list(source_posts or [])),
    )
    return _unique_topic_items(
        {
            "role": "gallery_axis",
            "label": candidate,
            "source_title": candidate,
        }
        for candidate in candidates[:6]
        if candidate
    )


def _role_quotas(total_count: int, available_roles: Iterable[str]) -> dict[str, int]:
    total = max(1, int(total_count or 1))
    roles = set(available_roles)
    quotas = {role: 0 for role in roles}
    if not roles:
        return {"main_thread": total}

    desired = {
        "main_thread": max(1, round(total * 0.40)),
        "side_thread": max(0, round(total * 0.25)),
        "gallery_axis": max(0, math.ceil(total * 0.15)),
        "casual_detail": max(0, round(total * 0.10)),
    }
    if "gallery_axis" not in roles:
        desired["side_thread"] += desired["gallery_axis"]
        desired["gallery_axis"] = 0
    if "side_thread" not in roles:
        desired["main_thread"] += desired["side_thread"]
        desired["side_thread"] = 0
    if "casual_detail" not in roles:
        desired["side_thread"] += desired["casual_detail"]
        desired["casual_detail"] = 0

    assigned = 0
    for role, count in desired.items():
        if role in roles:
            quotas[role] = min(total - assigned, max(0, count))
            assigned += quotas[role]
    while assigned < total:
        for role in ("main_thread", "side_thread", "gallery_axis", "casual_detail"):
            if role in quotas:
                quotas[role] += 1
                assigned += 1
                if assigned >= total:
                    break
    return quotas


def _role_schedule(total_count: int, quotas: dict[str, int]) -> list[str]:
    order = [
        "main_thread",
        "side_thread",
        "main_thread",
        "gallery_axis",
        "casual_detail",
        "side_thread",
    ]
    remaining = dict(quotas)
    schedule: list[str] = []
    while len(schedule) < total_count and any(count > 0 for count in remaining.values()):
        for role in order:
            if remaining.get(role, 0) <= 0:
                continue
            schedule.append(role)
            remaining[role] -= 1
            if len(schedule) >= total_count:
                break
    return schedule[:total_count]


def build_conversation_plan(
    total_count: int,
    topic: object,
    *,
    gallery_id: str = "",
    source_posts: Iterable[dict] = (),
    purpose_slot_enabled: bool = True,
) -> dict:
    """Return a deterministic, gallery-agnostic conversation arc."""

    total = max(1, int(total_count or 1))
    source_posts = list(source_posts or [])
    seed_items = _seed_items(topic)
    source_items = _source_items(source_posts)
    gallery_items = _gallery_items(
        gallery_id,
        source_posts,
        enabled=purpose_slot_enabled,
    )

    items_by_role: dict[str, list[dict]] = {
        "main_thread": seed_items,
        "side_thread": source_items,
        "gallery_axis": gallery_items,
        "casual_detail": source_items[::2],
    }
    available_roles = [role for role, items in items_by_role.items() if items]
    if not available_roles:
        fallback = [
            {
                "role": "main_thread",
                "label": _clean(topic, limit=80),
                "family_tokens": tuple(sorted(_tokens(topic))),
            }
        ]
        items_by_role["main_thread"] = fallback
        available_roles = ["main_thread"]

    quotas = _role_quotas(total, available_roles)
    schedule = _role_schedule(total, quotas)
    assignments: list[dict] = []
    role_counts: Counter[str] = Counter()
    for index, role in enumerate(schedule, 1):
        items = items_by_role.get(role) or items_by_role.get("main_thread") or []
        item = items[role_counts[role] % len(items)] if items else {}
        stance_key, stance_rule = _STANCE_LANES[(index - 1) % len(_STANCE_LANES)]
        role_counts[role] += 1
        assignments.append(
            {
                "wave": index,
                "role": role,
                "role_rule": _ROLE_RULES.get(role, _ROLE_RULES["main_thread"]),
                "label": item.get("label", ""),
                "family_tokens": item.get("family_tokens", ()),
                "source_title": item.get("source_title", ""),
                "source_body": item.get("source_body", ""),
                "source_comment": item.get("source_comment", ""),
                "stance_key": stance_key,
                "stance_rule": stance_rule,
            }
        )

    return {
        "total_count": total,
        "quotas": quotas,
        "assignments": assignments,
    }


def batch_prompt_block(plan: dict | None) -> str:
    if not isinstance(plan, dict) or not plan.get("assignments"):
        return ""
    quotas = plan.get("quotas") if isinstance(plan.get("quotas"), dict) else {}
    quota_text = ", ".join(
        f"{role}={count}"
        for role, count in quotas.items()
        if int(count or 0) > 0
    )
    return "\n".join(
        [
            "[Conversation Arc]",
            f"- Batch distribution target: {quota_text or 'balanced small topics'}.",
            "- Do not solve repetition by announcing a topic change. Start directly from the next concrete object.",
            "- Main hot topics may recur, but one noun family should not dominate the batch.",
            "- Complaint/critique posts should stay below one third of the batch.",
            "- Prefer detail, small consequence, aside, soft counter, or a quiet standalone post.",
            "- Side and gallery-axis posts must not explain why the board needs variety.",
        ]
    )


def wave_prompt_block(
    plan: dict | None,
    wave_index: int,
    *,
    slot: str = "",
    used_titles: Iterable[str] = (),
) -> str:
    if not isinstance(plan, dict):
        return ""
    assignments = plan.get("assignments")
    if not isinstance(assignments, list) or not assignments:
        return ""
    index = max(1, int(wave_index or 1))
    assignment = assignments[(index - 1) % len(assignments)]
    used = [str(title).strip() for title in used_titles if str(title).strip()]
    recent = " / ".join(used[-4:])
    lines = [
        "[This Wave Conversation Role]",
        f"- Role: {assignment.get('role')} ({assignment.get('label')})",
        f"- Role rule: {assignment.get('role_rule')}",
        f"- Stance lane: {assignment.get('stance_key')} - {assignment.get('stance_rule')}",
        f"- Existing slot from generator: {slot or 'auto'}. Keep the slot, but use this role to choose a narrower angle.",
        "- If this role would repeat an existing title, keep the same general topic but switch the object, consequence, or sentence shape.",
    ]
    if assignment.get("source_title"):
        lines.append(f"- Candidate source title: {assignment.get('source_title')}")
    if assignment.get("source_comment"):
        lines.append(f"- Candidate comment hook: {assignment.get('source_comment')}")
    if recent:
        lines.append(f"- Recent accepted titles to avoid echoing: {recent}")
    return "\n".join(lines)
