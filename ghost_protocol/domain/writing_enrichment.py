"""Prompt-safe composition signals for richer draft generation.

This module does not encode gallery-specific topics.  It only reads the
current source set and turns visible structure into compact guidance:
title/body balance, comment density, and how much evidence a post usually
carries.  The generator can then vary drafts without becoming longer or more
analytical than the board rhythm allows.
"""

from __future__ import annotations

import random as _random
from collections import Counter
from statistics import median
from typing import Iterable


def _clean(value: object, *, limit: int = 400) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _comments_from(post: dict) -> list[str]:
    comments = post.get("comments")
    if comments is None:
        comments = post.get("existing_comments")
    if not isinstance(comments, list):
        return []
    return [_clean(item, limit=120) for item in comments if _clean(item, limit=120)]


def _posts_from(
    raw_data: dict | None = None,
    *,
    recent_posts: Iterable[dict] | None = None,
) -> list[dict]:
    raw_data = raw_data or {}
    candidates = raw_data.get("raw_posts")
    if not candidates and recent_posts is not None:
        candidates = list(recent_posts)
    if not isinstance(candidates, list):
        return []

    posts: list[dict] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        title = _clean(item.get("title") or item.get("source_title"), limit=220)
        content = _clean(item.get("content") or item.get("body"), limit=800)
        comments = _comments_from(item)
        if not title and not content and not comments:
            continue
        posts.append({"title": title, "content": content, "comments": comments})
    return posts


def _ratio(count: int, total: int) -> float:
    return round(count / total, 3) if total else 0.0


def _avg(values: list[int]) -> float:
    return round(sum(values) / len(values), 1) if values else 0.0


def _ending_family(value: str) -> str:
    text = _clean(value, limit=260).rstrip()
    if not text:
        return ""
    if text.endswith("?"):
        return "question"
    if text[-1] in {"ㅋ", "ㅎ"}:
        return "laugh"
    fragment_suffixes = (
        "아님",
        "아닌듯",
        "같음",
        "있음",
        "없음",
        "해야함",
        "되는듯",
        "보임",
        "느낌",
        "임",
        "함",
        "됨",
        "듯",
        "봄",
        "씀",
        "중",
        "각",
    )
    if text.endswith(fragment_suffixes):
        return "fragment"
    if text.endswith(("다", "네", "지", "야", "겠네", "같다", "보인다")):
        return "plain"
    return "open"


def _weighted_pick(
    weighted_items: list[tuple[str, float]],
    *,
    rng: _random.Random | object | None = None,
) -> str:
    choices = [(item, max(0.0, float(weight))) for item, weight in weighted_items]
    total = sum(weight for _, weight in choices)
    if total <= 0:
        return choices[0][0] if choices else ""
    random_source = rng or _random
    threshold = float(random_source.random()) * total
    running = 0.0
    for item, weight in choices:
        running += weight
        if threshold <= running:
            return item
    return choices[-1][0]


def build_composition_profile(
    raw_data: dict | None = None,
    *,
    style_profile: dict | None = None,
    recent_posts: Iterable[dict] | None = None,
) -> dict:
    """Build a compact profile describing how source posts are shaped."""

    posts = _posts_from(raw_data, recent_posts=recent_posts)
    titles = [post["title"] for post in posts if post["title"]]
    bodies = [post["content"] for post in posts if post["content"]]
    comments = [comment for post in posts for comment in post["comments"]]
    total = len(posts)

    title_lengths = [len(text) for text in titles]
    body_lengths = [len(text) for text in bodies]
    comment_lengths = [len(text) for text in comments]
    title_only = sum(1 for post in posts if post["title"] and len(post["content"]) < 12)
    short_body = sum(1 for text in bodies if len(text) <= 70)
    medium_body = sum(1 for text in bodies if 55 <= len(text) < 110)
    long_body = sum(1 for text in bodies if len(text) >= 110)
    expanded_body = sum(1 for text in bodies if len(text) >= 180)
    comment_posts = sum(1 for post in posts if post["comments"])
    long_comments = sum(1 for text in comments if len(text) >= 45)

    avg_title_len = _avg(title_lengths)
    avg_body_len = _avg(body_lengths)
    median_body_len = round(float(median(body_lengths)), 1) if body_lengths else 0.0
    title_only_ratio = _ratio(title_only, total)
    body_present_ratio = _ratio(len(bodies), total)
    short_body_ratio = _ratio(short_body, len(bodies))
    medium_body_ratio = _ratio(medium_body, len(bodies))
    long_body_ratio = _ratio(long_body, len(bodies))
    expanded_body_ratio = _ratio(expanded_body, len(bodies))
    comment_presence_ratio = _ratio(comment_posts, total)
    avg_comment_len = _avg(comment_lengths)
    long_comment_ratio = _ratio(long_comments, len(comments))
    ending_counts = Counter(
        family
        for family in (_ending_family(text) for text in [*titles, *bodies])
        if family
    )
    ending_total = sum(ending_counts.values())
    dominant_ending_family = ""
    dominant_ending_ratio = 0.0
    if ending_counts and ending_total:
        dominant_ending_family, dominant_count = ending_counts.most_common(1)[0]
        dominant_ending_ratio = round(dominant_count / ending_total, 3)

    if total == 0:
        shape = "unknown"
    elif title_only_ratio >= 0.55 or (avg_title_len <= 24 and avg_body_len <= 45):
        shape = "title_driven"
    elif avg_body_len <= 110 or short_body_ratio >= 0.65:
        shape = "title_plus_one_line"
    else:
        shape = "body_supporting"

    if avg_body_len >= 180:
        depth = "expanded"
    elif avg_body_len >= 70 or comment_presence_ratio >= 0.35:
        depth = "compact"
    else:
        depth = "shallow"

    profile = {
        "sample_size": total,
        "shape": shape,
        "depth": depth,
        "avg_title_len": avg_title_len,
        "avg_body_len": avg_body_len,
        "median_body_len": median_body_len,
        "title_only_ratio": title_only_ratio,
        "body_present_ratio": body_present_ratio,
        "short_body_ratio": short_body_ratio,
        "medium_body_ratio": medium_body_ratio,
        "long_body_ratio": long_body_ratio,
        "expanded_body_ratio": expanded_body_ratio,
        "comment_presence_ratio": comment_presence_ratio,
        "avg_comment_len": avg_comment_len,
        "long_comment_ratio": long_comment_ratio,
        "dominant_ending_family": dominant_ending_family,
        "dominant_ending_ratio": dominant_ending_ratio,
        "style_profile_sample_size": int((style_profile or {}).get("sample_size", 0) or 0),
    }
    profile["rules"] = composition_rules_from_profile(profile)
    profile["comment_rules"] = comment_rules_from_profile(profile)
    return profile


def composition_rules_from_profile(profile: dict) -> list[str]:
    """Translate structure metrics into draft instructions."""

    if int(profile.get("sample_size", 0) or 0) <= 0:
        return []

    shape = str(profile.get("shape") or "unknown")
    depth = str(profile.get("depth") or "shallow")
    rules: list[str] = []

    if shape == "title_driven":
        rules.append(
            "Most source posts are title-driven: put the concrete object and reaction in the title; keep the body empty-feeling or one short follow-up line."
        )
        rules.append(
            "Do not expand a title-only board rhythm into a briefing paragraph. If the title already carries the joke or judgment, the body should add only a tiny reason, number, or aftertaste."
        )
    elif shape == "title_plus_one_line":
        rules.append(
            "Use a title plus one supporting line. The body should not repeat the title; add one reason, comparison, small consequence, or sensory detail."
        )
    elif shape == "body_supporting":
        rules.append(
            "Source bodies carry more context: allow two short body lines, with line one reacting and line two adding evidence or consequence."
        )
    else:
        rules.append(
            "When the source shape is unclear, default to a compact title plus one concrete body line."
        )

    if depth == "expanded":
        rules.append("A slightly fuller body is acceptable, but keep it conversational rather than explanatory.")
    elif depth == "compact":
        rules.append("Keep the draft compact: one small point per post, no stacked summary nouns.")
    else:
        rules.append("Prefer low-attention drafts: short title, short body, no grand conclusion.")

    if float(profile.get("long_body_ratio", 0.0) or 0.0) >= 0.08:
        rules.append(
            "The source set includes real long bodies. Keep them as a minority lane: a fuller draft may use 3-5 short lines with one concrete detail, one contrast, and one low-key closing beat."
        )
    elif float(profile.get("medium_body_ratio", 0.0) or 0.0) >= 0.18:
        rules.append(
            "A medium draft is acceptable sometimes: two body lines that add detail instead of repeating the title."
        )

    if float(profile.get("title_only_ratio", 0.0) or 0.0) >= 0.45:
        rules.append("A body that feels like a caption is better than a complete essay.")
    if float(profile.get("body_present_ratio", 0.0) or 0.0) <= 0.35:
        rules.append("Avoid over-explaining; source bodies are often absent or minimal.")

    return rules[:5]


def comment_rules_from_profile(profile: dict) -> list[str]:
    """Translate structure metrics into comment-generation instructions."""

    if int(profile.get("sample_size", 0) or 0) <= 0:
        return []

    comment_presence = float(profile.get("comment_presence_ratio", 0.0) or 0.0)
    avg_comment_len = float(profile.get("avg_comment_len", 0.0) or 0.0)
    rules: list[str] = []

    if comment_presence <= 0.12:
        rules.append(
            "Comments are sparse in the source set, but do not default to silence: when a target post shares the same concrete object, number, game title, rule, price, or scene, prefer one short target comment over an empty array."
        )
    else:
        rules.append(
            "Comments are part of the rhythm. Prefer at least one target comment when a same-object target exists; attach to one concrete detail from the target post, not to the whole board mood."
        )

    if float(profile.get("long_comment_ratio", 0.0) or 0.0) >= 0.12:
        rules.append(
            "Some source comments are longer. A minority comment may use 3-4 short lines when it follows a concrete detail from the target post."
        )
    elif avg_comment_len and avg_comment_len <= 35:
        rules.append("Keep comments very short: one beat, one reaction, no full paragraph.")
    elif avg_comment_len >= 80:
        rules.append("A two- to four-line comment is acceptable when it adds a small reason or contrast.")
    else:
        rules.append("Use one compact sentence unless the target post already has a two-line comment rhythm.")

    rules.append(
        "The comment should share the post-writing contract but stay lower-stakes: prefer added detail, tiny objection, cost/time/rule friction, or dry aside over plain agreement."
    )
    rules.append(
        "Across a batch, aim for comments on roughly half of publishable drafts when suitable targets exist. Use 1 comment by default and 2 only when both targets clearly share the draft's object."
    )
    return rules[:4]


def prompt_block(profile: dict | None) -> str:
    """Render composition guidance for post-generation prompts."""

    if not isinstance(profile, dict) or not profile.get("rules"):
        return ""
    lines = [
        "[Composition Profile]",
        (
            "- Signals: "
            f"shape={profile.get('shape')}, "
            f"depth={profile.get('depth')}, "
            f"title_only={float(profile.get('title_only_ratio', 0.0) or 0.0):.0%}, "
            f"body_present={float(profile.get('body_present_ratio', 0.0) or 0.0):.0%}, "
            f"comment_posts={float(profile.get('comment_presence_ratio', 0.0) or 0.0):.0%}, "
            f"avg_title={profile.get('avg_title_len', 0)}, "
            f"avg_body={profile.get('avg_body_len', 0)}"
        ),
    ]
    lines.extend(f"- {rule}" for rule in profile.get("rules", []) if str(rule).strip())
    return "\n".join(lines)


def comment_prompt_block(profile: dict | None) -> str:
    """Render composition guidance for comment-generation prompts."""

    if not isinstance(profile, dict) or not profile.get("comment_rules"):
        return ""
    lines = ["[Comment Composition Profile]"]
    lines.extend(
        f"- {rule}" for rule in profile.get("comment_rules", []) if str(rule).strip()
    )
    lines.append(
        "- Attach comments to a concrete word or detail from the generated draft. Do not import an unrelated side topic just because it came from the same source thread."
    )
    lines.append(
        "- Active comment mode: if the target pool contains a post about the same game/card/rule/price/number/scene, write one compact comment instead of leaving target_comments empty."
    )
    lines.append(
        "- Do not make agreement the default. If a comment agrees, it must also add one target-specific noun, number, rule, price, or scene."
    )
    return "\n".join(lines)


def choose_length_lane(
    profile: dict | None,
    *,
    requested_length: str = "",
    rng: _random.Random | object | None = None,
) -> str:
    """Choose a per-draft length lane from the current source structure."""

    profile = profile or {}
    requested = str(requested_length or "")
    avg_body_len = float(profile.get("avg_body_len", 0.0) or 0.0)
    medium_ratio = float(profile.get("medium_body_ratio", 0.0) or 0.0)
    long_ratio = float(profile.get("long_body_ratio", 0.0) or 0.0)
    expanded_ratio = float(profile.get("expanded_body_ratio", 0.0) or 0.0)
    comment_presence = float(profile.get("comment_presence_ratio", 0.0) or 0.0)

    long_supported = long_ratio >= 0.08 or expanded_ratio >= 0.04 or avg_body_len >= 100
    medium_supported = medium_ratio >= 0.15 or avg_body_len >= 85 or comment_presence >= 0.32

    if "아주 짧게" in requested:
        return "short"
    if "짧게" in requested and "아주" not in requested:
        return _weighted_pick([("short", 0.72), ("compact", 0.28)], rng=rng)
    if any(token in requested for token in ("길게", "장문", "상세")):
        if long_supported:
            return _weighted_pick(
                [("medium", 0.36), ("long", 0.54), ("compact", 0.10)],
                rng=rng,
            )
        return _weighted_pick([("medium", 0.68), ("compact", 0.32)], rng=rng)

    medium_weight = 0.20 if medium_supported else 0.08
    long_weight = 0.10 if long_supported else 0.0
    compact_weight = 0.34 if medium_supported else 0.40
    short_weight = max(0.30, 1.0 - medium_weight - long_weight - compact_weight)
    return _weighted_pick(
        [
            ("short", short_weight),
            ("compact", compact_weight),
            ("medium", medium_weight),
            ("long", long_weight),
        ],
        rng=rng,
    )


def choose_voice_lane(
    profile: dict | None,
    *,
    rng: _random.Random | object | None = None,
) -> str:
    """Choose a per-draft ending/voice lane to avoid one-note endings."""

    profile = profile or {}
    dominant = str(profile.get("dominant_ending_family") or "")
    ratio = float(profile.get("dominant_ending_ratio", 0.0) or 0.0)
    if dominant == "fragment" and ratio >= 0.42:
        return _weighted_pick(
            [
                ("plain", 0.42),
                ("mixed", 0.31),
                ("fragment", 0.16),
                ("question", 0.05),
                ("laugh", 0.06),
            ],
            rng=rng,
        )
    if dominant == "question" and ratio >= 0.35:
        return _weighted_pick(
            [("plain", 0.48), ("mixed", 0.30), ("question", 0.08), ("fragment", 0.14)],
            rng=rng,
        )
    return _weighted_pick(
        [
            ("plain", 0.30),
            ("mixed", 0.31),
            ("fragment", 0.22),
            ("question", 0.07),
            ("laugh", 0.08),
        ],
        rng=rng,
    )


_LENGTH_LANE_RULES: dict[str, str] = {
    "short": (
        "Length lane SHORT: title carries most of the post. Body is empty-feeling "
        "or one low-key line under 80 Korean characters."
    ),
    "compact": (
        "Length lane COMPACT: title plus 1-2 short body sentences. Body adds one "
        "reason, number, comparison, or aftertaste."
    ),
    "medium": (
        "Length lane MEDIUM: use 2-3 short body lines. Line 1 reacts, line 2 adds "
        "a concrete detail or contrast, optional line 3 closes lightly."
    ),
    "long": (
        "Length lane FULLER: allow 3-5 short lines, roughly 220-520 Korean "
        "characters. Keep it conversational: one scene/detail, one reason or "
        "contrast, one low-key closing beat. Do not turn it into a briefing."
    ),
}

_VOICE_LANE_RULES: dict[str, str] = {
    "plain": (
        "Voice lane PLAIN: avoid ending every sentence with board-fragment endings "
        "like 함/임/듯/아님. Use ordinary casual endings such as 같다, 보인다, 했네, "
        "아니다 when they fit."
    ),
    "mixed": (
        "Voice lane MIXED: one fragment ending is fine, but pair it with a normal "
        "casual sentence so the draft does not become all 음슴체."
    ),
    "fragment": (
        "Voice lane FRAGMENT: use the board-fragment rhythm only once or twice. "
        "Do not make both title and every body line end with the same suffix."
    ),
    "question": (
        "Voice lane QUESTION: use at most one real question across title/body, only for "
        "recommendation, rule, price, or availability checks. End it with ?. If the question "
        "is just curiosity, rewrite it as a small statement."
    ),
    "laugh": (
        "Voice lane LAUGH: a short ㅋㅋ/ㄷㄷ tail is allowed once if the source rhythm "
        "supports it. Do not attach laughter to every sentence."
    ),
}

_VOICE_LANE_RULES.update(
    {
        "plain": (
            "Voice lane PLAIN: avoid ending every sentence with board-fragment endings "
            "like 함/임/듯/아님. Use ordinary casual endings such as 아닌가, 같긴 함, "
            "모르겠네, 봐야 될 듯 when they fit."
        ),
        "mixed": (
            "Voice lane MIXED: one fragment ending is fine, but pair it with a normal "
            "casual sentence so the draft does not become all 음슴체."
        ),
        "laugh": (
            "Voice lane LAUGH: a short ㅋㅋ/ㅎㅎ tail is allowed once if the source rhythm "
            "supports it. Do not attach laughter to every sentence."
        ),
    }
)

_COMMENT_MOVE_RULES: dict[str, str] = {
    "detail": (
        "Comment move DETAIL: add one small target-specific detail such as a card name, "
        "component, price, player count, turn step, photo state, or storage issue."
    ),
    "counter": (
        "Comment move SMALL COUNTER: push back with one condition or exception. "
        "Do not turn it into a debate opener."
    ),
    "friction": (
        "Comment move FRICTION: react through time, money, cleanup, shipping, table space, "
        "rule lookup, sleeve/storage, or replay burden."
    ),
    "rule_hook": (
        "Comment move RULE/COMPONENT: attach to a rule, card effect, component, expansion, "
        "edition, or setup detail instead of broad agreement."
    ),
    "aside": (
        "Comment move DRY ASIDE: leave a small joke or aftertaste tied to the target object. "
        "Avoid generic 'same' or 'true' reactions."
    ),
    "next_step": (
        "Comment move NEXT STEP: suggest one tiny action such as checking condition, player count, "
        "rulebook wording, price history, or a photo angle."
    ),
}


_POST_SHAPE_RULES: dict[str, str] = {
    "object_reaction": (
        "post_shape=object_reaction: react to one visible object, title phrase, "
        "rule/condition, person-in-scene, number, or result from the source."
    ),
    "detail_add": (
        "post_shape=detail_add: add one small detail the source implies, such as "
        "a condition, timing, cost, step, count, photo state, setup, or result."
    ),
    "small_counter": (
        "post_shape=small_counter: push back on one narrow point without turning "
        "the draft into criticism of the whole board."
    ),
    "comparison": (
        "post_shape=comparison: compare two nearby conditions, numbers, versions, "
        "moments, or outcomes from the collected posts."
    ),
    "friction_note": (
        "post_shape=friction_note: respond through a practical friction such as "
        "time, money, space, waiting, setup, cleanup, effort, or uncertainty."
    ),
    "comment_bridge": (
        "post_shape=comment_bridge: continue from a target comment or reply-like "
        "phrase, but do not quote it as a formal summary."
    ),
    "quiet_seed": (
        "post_shape=quiet_seed: start a nearby small topic from a source detail "
        "without announcing a topic change."
    ),
}

_STANCE_RULES: dict[str, str] = {
    "low_agree": "stance=low_agree: lightly accept the premise, then add one concrete limit.",
    "small_counter": "stance=small_counter: disagree with one detail, not the whole topic.",
    "condition": "stance=condition: make the reaction depend on one visible condition.",
    "friction": "stance=friction: make the point through effort, cost, time, or inconvenience.",
    "dry_joke": "stance=dry_joke: use one dry joke or aftertaste, without punchline pressure.",
    "watching": "stance=watching: stay observational and low-stakes, not instructive.",
}

_EVIDENCE_ANCHOR_RULES: dict[str, str] = {
    "title_object": (
        "evidence_anchor=title_object: title must include one concrete noun or named "
        "object visible in the source, not a broad abstract label."
    ),
    "number_or_time": (
        "evidence_anchor=number_or_time: use one source number, count, date/time, "
        "rank, price, score, page count, or interval."
    ),
    "condition_or_rule": (
        "evidence_anchor=condition_or_rule: use one rule, condition, cause, setup, "
        "constraint, exception, or requirement visible in the source."
    ),
    "scene_or_action": (
        "evidence_anchor=scene_or_action: use one action, camera/photo state, physical "
        "scene, result, or next step visible in the source."
    ),
    "comment_phrase": (
        "evidence_anchor=comment_phrase: continue from one target comment phrase or "
        "replyable fragment, but paraphrase enough to avoid copy-paste."
    ),
    "cost_or_friction": (
        "evidence_anchor=cost_or_friction: attach the draft to cost, time, effort, "
        "space, delay, waiting, setup, cleanup, or risk."
    ),
}

_COMMENT_RELATION_RULES: dict[str, str] = {
    "supplement": (
        "comment_relation=supplement: add one missing detail to the target post."
    ),
    "counter_example": (
        "comment_relation=counter_example: give a small exception or alternate case."
    ),
    "condition": (
        "comment_relation=condition: make the agreement/disagreement depend on one condition."
    ),
    "friction": (
        "comment_relation=friction: react through time, money, effort, setup, cleanup, or risk."
    ),
    "rule_detail": (
        "comment_relation=rule_detail: attach to a rule, procedure, component, step, or wording."
    ),
    "dry_aside": (
        "comment_relation=dry_aside: leave one low-key joke or aftertaste tied to the target."
    ),
    "next_step": (
        "comment_relation=next_step: suggest one small check, comparison, or thing to look at next."
    ),
}

_COMMENT_ANCHOR_RULES: dict[str, str] = {
    "target_noun": "target_anchor=target_noun: reuse the target's concrete noun only if it is not sensitive.",
    "target_number": "target_anchor=target_number: react to a number, count, price, time, or score.",
    "target_condition": "target_anchor=target_condition: react to a condition, exception, rule, or setup.",
    "target_scene": "target_anchor=target_scene: react to the target's scene, photo, result, or action.",
    "target_aftertaste": "target_anchor=target_aftertaste: react to the target's implication rather than agreement.",
}


def choose_post_shape(
    profile: dict | None,
    *,
    rng: _random.Random | object | None = None,
) -> str:
    """Choose what kind of post this call should make."""

    profile = profile or {}
    shape = str(profile.get("shape") or "")
    comment_presence = float(profile.get("comment_presence_ratio", 0.0) or 0.0)
    long_body_ratio = float(profile.get("long_body_ratio", 0.0) or 0.0)

    weights = [
        ("object_reaction", 0.23),
        ("detail_add", 0.20),
        ("small_counter", 0.15),
        ("comparison", 0.14),
        ("friction_note", 0.14),
        ("comment_bridge", 0.07),
        ("quiet_seed", 0.07),
    ]
    if shape == "title_driven":
        weights = [
            ("object_reaction", 0.28),
            ("detail_add", 0.18),
            ("small_counter", 0.13),
            ("comparison", 0.13),
            ("friction_note", 0.13),
            ("comment_bridge", 0.07),
            ("quiet_seed", 0.08),
        ]
    elif long_body_ratio >= 0.25:
        weights = [
            ("object_reaction", 0.16),
            ("detail_add", 0.24),
            ("small_counter", 0.14),
            ("comparison", 0.18),
            ("friction_note", 0.15),
            ("comment_bridge", 0.06),
            ("quiet_seed", 0.07),
        ]
    if comment_presence >= 0.25:
        weights = [(key, weight + (0.08 if key == "comment_bridge" else 0.0)) for key, weight in weights]
    return _weighted_pick(weights, rng=rng)


def choose_stance(
    profile: dict | None,
    *,
    rng: _random.Random | object | None = None,
) -> str:
    """Choose a low-key stance for one draft."""

    profile = profile or {}
    depth = str(profile.get("depth") or "")
    if depth == "expanded":
        weights = [
            ("low_agree", 0.17),
            ("small_counter", 0.18),
            ("condition", 0.22),
            ("friction", 0.16),
            ("dry_joke", 0.10),
            ("watching", 0.17),
        ]
    else:
        weights = [
            ("low_agree", 0.20),
            ("small_counter", 0.15),
            ("condition", 0.18),
            ("friction", 0.18),
            ("dry_joke", 0.14),
            ("watching", 0.15),
        ]
    return _weighted_pick(weights, rng=rng)


def choose_evidence_anchor(
    profile: dict | None,
    *,
    rng: _random.Random | object | None = None,
) -> str:
    """Choose the concrete source detail the draft must lean on."""

    profile = profile or {}
    avg_body_len = float(profile.get("avg_body_len", 0.0) or 0.0)
    comment_presence = float(profile.get("comment_presence_ratio", 0.0) or 0.0)
    weights = [
        ("title_object", 0.25),
        ("number_or_time", 0.16),
        ("condition_or_rule", 0.17),
        ("scene_or_action", 0.17),
        ("comment_phrase", 0.08),
        ("cost_or_friction", 0.17),
    ]
    if avg_body_len >= 45:
        weights = [
            ("title_object", 0.18),
            ("number_or_time", 0.15),
            ("condition_or_rule", 0.22),
            ("scene_or_action", 0.20),
            ("comment_phrase", 0.07),
            ("cost_or_friction", 0.18),
        ]
    if comment_presence >= 0.25:
        weights = [(key, weight + (0.07 if key == "comment_phrase" else 0.0)) for key, weight in weights]
    return _weighted_pick(weights, rng=rng)


def choose_comment_relation(
    profile: dict | None,
    *,
    rng: _random.Random | object | None = None,
) -> str:
    """Choose how a generated comment relates to its target post."""

    profile = profile or {}
    long_ratio = float(profile.get("long_comment_ratio", 0.0) or 0.0)
    avg_comment_len = float(profile.get("avg_comment_len", 0.0) or 0.0)
    if long_ratio >= 0.12 or avg_comment_len >= 65:
        return _weighted_pick(
            [
                ("supplement", 0.20),
                ("counter_example", 0.17),
                ("condition", 0.18),
                ("friction", 0.15),
                ("rule_detail", 0.14),
                ("dry_aside", 0.08),
                ("next_step", 0.08),
            ],
            rng=rng,
        )
    return _weighted_pick(
        [
            ("supplement", 0.20),
            ("counter_example", 0.14),
            ("condition", 0.17),
            ("friction", 0.18),
            ("rule_detail", 0.15),
            ("dry_aside", 0.11),
            ("next_step", 0.05),
        ],
        rng=rng,
    )


def choose_comment_anchor(
    profile: dict | None,
    *,
    rng: _random.Random | object | None = None,
) -> str:
    """Choose what target-post detail a generated comment should attach to."""

    profile = profile or {}
    avg_comment_len = float(profile.get("avg_comment_len", 0.0) or 0.0)
    if avg_comment_len >= 55:
        weights = [
            ("target_noun", 0.22),
            ("target_number", 0.18),
            ("target_condition", 0.24),
            ("target_scene", 0.20),
            ("target_aftertaste", 0.16),
        ]
    else:
        weights = [
            ("target_noun", 0.28),
            ("target_number", 0.16),
            ("target_condition", 0.18),
            ("target_scene", 0.20),
            ("target_aftertaste", 0.18),
        ]
    return _weighted_pick(weights, rng=rng)


def choose_comment_move(
    profile: dict | None,
    *,
    rng: _random.Random | object | None = None,
) -> str:
    """Choose a per-comment action so target comments do not collapse into agreement."""

    profile = profile or {}
    avg_comment_len = float(profile.get("avg_comment_len", 0.0) or 0.0)
    long_ratio = float(profile.get("long_comment_ratio", 0.0) or 0.0)
    if long_ratio >= 0.12 or avg_comment_len >= 65:
        return _weighted_pick(
            [
                ("detail", 0.25),
                ("counter", 0.18),
                ("friction", 0.20),
                ("rule_hook", 0.17),
                ("aside", 0.10),
                ("next_step", 0.10),
            ],
            rng=rng,
        )
    return _weighted_pick(
        [
            ("detail", 0.25),
            ("counter", 0.16),
            ("friction", 0.20),
            ("rule_hook", 0.18),
            ("aside", 0.14),
            ("next_step", 0.07),
        ],
        rng=rng,
    )


def generation_variation_block(
    profile: dict | None,
    *,
    requested_length: str = "",
    rng: _random.Random | object | None = None,
) -> str:
    """Render one per-call variation lane for post generation."""

    if not isinstance(profile, dict) or int(profile.get("sample_size", 0) or 0) <= 0:
        return ""
    length_lane = choose_length_lane(profile, requested_length=requested_length, rng=rng)
    voice_lane = choose_voice_lane(profile, rng=rng)
    post_shape = choose_post_shape(profile, rng=rng)
    stance = choose_stance(profile, rng=rng)
    evidence_anchor = choose_evidence_anchor(profile, rng=rng)
    lines = [
        "[This Draft Variation]",
        f"- {_LENGTH_LANE_RULES.get(length_lane, _LENGTH_LANE_RULES['compact'])}",
        f"- {_VOICE_LANE_RULES.get(voice_lane, _VOICE_LANE_RULES['mixed'])}",
        "- The variation lane overrides only this one draft. Keep the source topic and persona intact.",
        "[Draft Card]",
        f"- {_POST_SHAPE_RULES.get(post_shape, _POST_SHAPE_RULES['object_reaction'])}",
        f"- {_STANCE_RULES.get(stance, _STANCE_RULES['watching'])}",
        f"- {_EVIDENCE_ANCHOR_RULES.get(evidence_anchor, _EVIDENCE_ANCHOR_RULES['title_object'])}",
        f"- length_lane={length_lane}: follow the selected length lane above before adding persona flavor.",
        f"- ending_style={voice_lane}: use the selected voice lane above, but do not expose this label.",
        "- Satisfy the Draft Card before persona color. If the chosen anchor is not visible in the source, switch to another visible source object instead of inventing one.",
    ]
    lines.append(
        "- Avoid the safe default endings piling up across the batch: 신기함, 애매함, 궁금함, 좋겠다, 같음, 듯. If the same topic appears again, switch to a concrete scene, number, comparison, or tiny joke."
    )
    lines.append(
        "- Do not finish with empty familiarity or invented memory: 이름 왜 익숙함, 어디서 본 것 같음, 나도 해봄, 막상 해보면. Replace them with a visible condition from the source."
    )
    if (
        str(profile.get("dominant_ending_family") or "") == "fragment"
        and float(profile.get("dominant_ending_ratio", 0.0) or 0.0) >= 0.42
    ):
        lines.append(
            "- Source endings lean toward board fragments. Borrow the rhythm lightly, but do not force every line into 함/임/듯/아님."
        )
    return "\n".join(lines)


def comment_length_rule(
    profile: dict | None,
    *,
    rng: _random.Random | object | None = None,
) -> str:
    """Choose a comment length rule from source comment density and length."""

    profile = profile or {}
    avg_comment_len = float(profile.get("avg_comment_len", 0.0) or 0.0)
    long_ratio = float(profile.get("long_comment_ratio", 0.0) or 0.0)
    comment_presence = float(profile.get("comment_presence_ratio", 0.0) or 0.0)

    if comment_presence <= 0.08:
        return "댓글이 거의 없는 리듬이다. 타겟 글에 붙일 구체 꼬투리가 없으면 빈 배열로 둔다."
    if long_ratio >= 0.12 or avg_comment_len >= 70:
        return _weighted_pick(
            [
                ("1줄. 낮은 반응 하나만 둔다.", 0.40),
                ("2줄. 첫 줄 반응, 둘째 줄 구체 이유나 딴지 한 마디.", 0.35),
                (
                    "3~5줄. 타겟 글의 본문·기존 댓글 디테일이 충분할 때만 작은 근거와 반박을 이어 쓴다. 각 줄은 짧게.",
                    0.25,
                ),
            ],
            rng=rng,
        )
    if avg_comment_len >= 55:
        return _weighted_pick(
            [
                ("1줄. 낮은 반응 하나만 둔다.", 0.48),
                ("2줄. 첫 줄 반응, 둘째 줄 구체 이유나 딴지 한 마디.", 0.42),
                ("3줄 이내. 타겟 글에 이미 긴 댓글 흐름이 있을 때만 허용한다.", 0.10),
            ],
            rng=rng,
        )
    return _weighted_pick(
        [
            ("1줄. 짧게 반응만 둔다.", 0.62),
            ("2줄. 첫 줄 반응, 둘째 줄 아주 짧은 이유.", 0.38),
        ],
        rng=rng,
    )


def comment_variation_block(
    profile: dict | None,
    *,
    rng: _random.Random | object | None = None,
) -> str:
    """Render per-call comment variation guidance."""

    if not isinstance(profile, dict) or int(profile.get("sample_size", 0) or 0) <= 0:
        return ""
    voice_lane = choose_voice_lane(profile, rng=rng)
    comment_move = choose_comment_move(profile, rng=rng)
    comment_relation = choose_comment_relation(profile, rng=rng)
    comment_anchor = choose_comment_anchor(profile, rng=rng)
    lines = [
        "[This Comment Variation]",
        f"- {_VOICE_LANE_RULES.get(voice_lane, _VOICE_LANE_RULES['mixed'])}",
        f"- {_COMMENT_MOVE_RULES.get(comment_move, _COMMENT_MOVE_RULES['detail'])}",
        "[Comment Relation Card]",
        f"- {_COMMENT_RELATION_RULES.get(comment_relation, _COMMENT_RELATION_RULES['supplement'])}",
        f"- {_COMMENT_ANCHOR_RULES.get(comment_anchor, _COMMENT_ANCHOR_RULES['target_noun'])}",
        "- Satisfy the Comment Relation Card before adding tone. Do not expose card labels in the final comment.",
        "- A longer comment is allowed only when it follows a concrete target-post detail; otherwise keep it short or return an empty array.",
        "- Plain agreement alone is not enough; add a concrete noun, number, rule, cost, or scene from the target post.",
        "- Avoid hedge-only endings such as 같기도 함, 심하긴 함, 될 듯, 궁금함 unless a concrete target detail appears in the same comment.",
    ]
    return "\n".join(lines)
