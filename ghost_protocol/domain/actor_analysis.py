"""Actor-level briefing from public board snapshots.

The analyzer deliberately works without an LLM.  It clusters publicly visible
board handles/IP hints into pseudonymous "actors" and summarizes only observed
posting behaviour.  It does not try to identify real people.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping


_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣_]{2,}")
_LAUGH_RE = re.compile(r"(ㅋ{2,}|ㅎ{2,}|lol|www)", re.IGNORECASE)
_QUESTION_RE = re.compile(r"[?？]|(임|냐|나|가|듯|아님|맞음)\s*$")
_STOPWORDS = {
    "이거",
    "그거",
    "저거",
    "그냥",
    "진짜",
    "너무",
    "좀",
    "뭔",
    "왜",
    "요즘",
    "오늘",
    "내일",
    "ㅋㅋ",
    "ㅋㅋㅋ",
    "같음",
    "아님",
    "있는",
    "없는",
    "하는",
    "해서",
    "보면",
    "다시",
}


@dataclass
class _ActorBucket:
    actor_key: str
    display_label: str
    identity_type: str
    posts: int = 0
    comments: int = 0
    terms: Counter[str] = field(default_factory=Counter)
    observed_hours: set[str] = field(default_factory=set)
    observations: list[dict[str, Any]] = field(default_factory=list)
    char_lengths: list[int] = field(default_factory=list)
    laugh_count: int = 0
    question_count: int = 0


def _clean(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _first_text(mapping: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = _clean(mapping.get(key))
        if value:
            return value
    return ""


def _stable_hash(parts: Iterable[str]) -> str:
    raw = "|".join(part.strip() for part in parts if part and part.strip())
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _mask_identity(value: str, *, keep: int = 3) -> str:
    text = _clean(value)
    if not text:
        return ""
    if len(text) <= keep + 1:
        return text[:1] + "*"
    return text[:keep] + "*"


def _post_identity(post: Mapping[str, Any], gallery_id: str) -> tuple[str, str, str] | None:
    author = _first_text(post, ("author", "nickname", "name", "writer", "user_name"))
    user_id = _first_text(post, ("user_id", "user_key", "fixed_id", "uid", "gallog"))
    ip_hint = _first_text(post, ("ip_hash", "ip", "ip_hint", "author_ip"))

    if not (author or user_id or ip_hint):
        return None

    identity_type = "fixed" if user_id else ("ip" if ip_hint else "nickname")
    if user_id:
        hash_parts = [gallery_id, identity_type, user_id]
    elif ip_hint:
        hash_parts = [gallery_id, identity_type, ip_hint, author or ""]
    else:
        hash_parts = [gallery_id, identity_type, author]
    key = f"actor:{_stable_hash(hash_parts)}"
    label_source = author or user_id or ip_hint
    if user_id:
        label = f"{_mask_identity(author or user_id)} · fixed"
    elif ip_hint:
        label = f"{_mask_identity(author or 'anon')} · {ip_hint}"
    else:
        label = _mask_identity(label_source)
    return key, label, identity_type


def _comment_identity(comment: Mapping[str, Any], gallery_id: str) -> tuple[str, str, str] | None:
    return _post_identity(comment, gallery_id)


def _created_hour(value: object) -> str:
    text = _clean(value)
    if not text:
        return ""
    match = re.search(r"\b([01]?\d|2[0-3]):[0-5]\d", text)
    if match:
        return f"{int(match.group(1)):02d}"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M:%S", "%m.%d %H:%M:%S", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return f"{parsed.hour:02d}"
        except ValueError:
            continue
    return ""


def _tokens(text: str) -> list[str]:
    found = []
    for token in _TOKEN_RE.findall(text):
        norm = token.lower()
        if norm in _STOPWORDS:
            continue
        if len(norm) <= 1:
            continue
        found.append(norm)
    return found


def _excerpt(text: str, limit: int = 120) -> str:
    compact = _clean(text)
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _add_observation(
    bucket: _ActorBucket,
    *,
    kind: str,
    post_no: str,
    comment_id: str = "",
    title: str = "",
    content: str = "",
    created_at: str = "",
) -> None:
    text = _clean(f"{title} {content}")
    if kind == "post":
        bucket.posts += 1
    else:
        bucket.comments += 1
    bucket.terms.update(_tokens(text))
    if created_at:
        hour = _created_hour(created_at)
        if hour:
            bucket.observed_hours.add(hour)
    if text:
        bucket.char_lengths.append(len(text))
        if _LAUGH_RE.search(text):
            bucket.laugh_count += 1
        if _QUESTION_RE.search(text):
            bucket.question_count += 1

    bucket.observations.append(
        {
            "kind": kind,
            "post_no": post_no,
            "comment_id": comment_id,
            "title": _excerpt(title, 80),
            "excerpt": _excerpt(content or title, 140),
            "created_at": created_at,
        }
    )


def _style_summary(bucket: _ActorBucket) -> dict[str, Any]:
    total = max(1, bucket.posts + bucket.comments)
    avg_chars = sum(bucket.char_lengths) / len(bucket.char_lengths) if bucket.char_lengths else 0.0
    return {
        "avg_chars": round(avg_chars, 1),
        "laugh_rate": round(bucket.laugh_count / total, 3),
        "question_rate": round(bucket.question_count / total, 3),
        "long_text_ratio": round(sum(1 for n in bucket.char_lengths if n >= 80) / max(1, len(bucket.char_lengths)), 3),
    }


def _resident_score(bucket: _ActorBucket) -> float:
    total = bucket.posts + bucket.comments
    mix_bonus = 0.25 if bucket.posts and bucket.comments else 0.0
    hour_bonus = min(0.35, len(bucket.observed_hours) * 0.07)
    volume = min(1.0, math.log1p(total) / math.log(12))
    return round(min(1.0, volume * 0.65 + mix_bonus + hour_bonus), 3)


def _actor_payload(bucket: _ActorBucket, *, max_observations: int) -> dict[str, Any]:
    total = bucket.posts + bucket.comments
    top_terms = [term for term, _ in bucket.terms.most_common(10)]
    return {
        "actor_key": bucket.actor_key,
        "display_label": bucket.display_label,
        "identity_type": bucket.identity_type,
        "post_count": bucket.posts,
        "comment_count": bucket.comments,
        "total_count": total,
        "active_hours": sorted(bucket.observed_hours),
        "top_terms": top_terms,
        "style": _style_summary(bucket),
        "scores": {
            "resident_score": _resident_score(bucket),
            "activity_score": round(min(1.0, math.log1p(total) / math.log(20)), 3),
        },
        "observations": bucket.observations[:max_observations],
    }


def analyze_actors(
    raw_posts: Iterable[Mapping[str, Any]] | None,
    *,
    gallery_id: str,
    max_actors: int = 8,
    max_observations_per_actor: int = 6,
) -> dict[str, Any]:
    """Cluster public board identities and summarize observed behaviour."""

    posts = [post for post in list(raw_posts or []) if isinstance(post, Mapping)]
    buckets: dict[str, _ActorBucket] = {}
    skipped_comments_without_identity = 0

    def get_bucket(identity: tuple[str, str, str]) -> _ActorBucket:
        actor_key, label, identity_type = identity
        if actor_key not in buckets:
            buckets[actor_key] = _ActorBucket(
                actor_key=actor_key,
                display_label=label,
                identity_type=identity_type,
            )
        return buckets[actor_key]

    for post in posts:
        post_no = _clean(post.get("post_no") or post.get("post_id") or post.get("no"))
        title = _clean(post.get("source_title") or post.get("title"))
        content = _clean(post.get("content"))
        created_at = _clean(post.get("created_at"))

        identity = _post_identity(post, gallery_id)
        if identity:
            _add_observation(
                get_bucket(identity),
                kind="post",
                post_no=post_no,
                title=title,
                content=content,
                created_at=created_at,
            )

        for idx, comment in enumerate(list(post.get("comments") or []), 1):
            if not isinstance(comment, Mapping):
                skipped_comments_without_identity += 1
                continue
            c_identity = _comment_identity(comment, gallery_id)
            if not c_identity:
                skipped_comments_without_identity += 1
                continue
            c_content = _first_text(comment, ("content", "text", "comment", "body"))
            c_created = _first_text(comment, ("created_at", "date", "time"))
            c_id = _first_text(comment, ("comment_id", "cmt_no", "id")) or str(idx)
            _add_observation(
                get_bucket(c_identity),
                kind="comment",
                post_no=post_no,
                comment_id=c_id,
                title=title,
                content=c_content,
                created_at=c_created or created_at,
            )

    actors = [_actor_payload(bucket, max_observations=max_observations_per_actor) for bucket in buckets.values()]
    actors.sort(
        key=lambda item: (
            item["scores"]["resident_score"],
            item["total_count"],
            item["post_count"],
        ),
        reverse=True,
    )
    visible = actors[: max(1, int(max_actors or 8))]
    total_posts = sum(actor["post_count"] for actor in actors)
    total_comments = sum(actor["comment_count"] for actor in actors)

    return {
        "version": 1,
        "gallery_id": gallery_id,
        "summary": {
            "source_post_count": len(posts),
            "actor_count": len(actors),
            "major_actor_count": len(visible),
            "observed_post_count": total_posts,
            "observed_comment_count": total_comments,
            "skipped_comment_count": skipped_comments_without_identity,
            "resident_like_count": sum(1 for actor in actors if actor["scores"]["resident_score"] >= 0.55),
            "post_heavy_count": sum(1 for actor in actors if actor["post_count"] > actor["comment_count"]),
            "comment_heavy_count": sum(1 for actor in actors if actor["comment_count"] > actor["post_count"]),
        },
        "actors": visible,
    }
