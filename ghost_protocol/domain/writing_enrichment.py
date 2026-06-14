"""Prompt-safe composition signals for richer draft generation.

This module does not encode gallery-specific topics.  It only reads the
current source set and turns visible structure into compact guidance:
title/body balance, comment density, and how much evidence a post usually
carries.  The generator can then vary drafts without becoming longer or more
analytical than the board rhythm allows.
"""

from __future__ import annotations

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
    comment_posts = sum(1 for post in posts if post["comments"])

    avg_title_len = _avg(title_lengths)
    avg_body_len = _avg(body_lengths)
    median_body_len = round(float(median(body_lengths)), 1) if body_lengths else 0.0
    title_only_ratio = _ratio(title_only, total)
    body_present_ratio = _ratio(len(bodies), total)
    short_body_ratio = _ratio(short_body, len(bodies))
    comment_presence_ratio = _ratio(comment_posts, total)
    avg_comment_len = _avg(comment_lengths)

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
        "comment_presence_ratio": comment_presence_ratio,
        "avg_comment_len": avg_comment_len,
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
            "Comments are sparse in the source set. Generate target comments only when the target post has a clear hook; otherwise return an empty array."
        )
    else:
        rules.append(
            "Comments are part of the rhythm. Attach to one concrete detail from the target post, not to the whole board mood."
        )

    if avg_comment_len and avg_comment_len <= 35:
        rules.append("Keep comments very short: one beat, one reaction, no full paragraph.")
    elif avg_comment_len >= 80:
        rules.append("A two-line comment is acceptable when it adds a small reason or contrast.")
    else:
        rules.append("Use one compact sentence unless the target post already has a two-line comment rhythm.")

    rules.append(
        "The comment should feel lower-stakes than the post: agreement, tiny objection, added detail, or dry aside."
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
    return "\n".join(lines)
