"""Gallery-specific writing style signals.

The generator already has static gallery contexts, but the same gallery can
shift its visible writing habits from hour to hour. This module extracts a
small, prompt-safe style profile from the currently collected titles/comments
so generation can mirror the board's surface rhythm without hardcoding each
topic.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

from ghost_protocol import prompt_manager as pm
from ghost_protocol.domain import gallery_purpose


_SHORTENER_RE = re.compile(r"(?:ㄹㅇ|ㅇㅇ|ㄷㄷ|ㅅㅂ|ㅈㄴ|ㅁㅊ|ㅈㄹ|ㅂㅅ|ㅁㅌㅊ|ㅇㅈ)")
_LAUGH_RE = re.compile(r"[ㅋㅎ]{2,}")
_CASUAL_ENDINGS = ("냐", "노", "네", "듯", "임", "함", "나", "냐고", "아님", "맞냐", "같음")
_QUESTION_ENDING_RE = re.compile(
    r"(?:\?|냐|었나|았나|했나|됐나|되나|있나|없나|바뀌나|나오나|보나|"
    r"가나|오나|일까|할까|볼까|갈까|올까|걸까|아님|아닌가|맞나|맞냐|"
    r"건가|거냐|될까|않나|않았나|인가|인지|뭐임)$"
)
_ARROW_MARKERS = ("<<", "<-", "->")


def _compact_texts(texts: Iterable[object], *, limit: int = 220) -> list[str]:
    clean: list[str] = []
    for value in texts:
        text = " ".join(str(value or "").split())
        if text:
            clean.append(text[:160])
        if len(clean) >= limit:
            break
    return clean


def _ratio(count: int, total: int) -> float:
    return round(count / total, 3) if total else 0.0


def _ending(text: str) -> str:
    stripped = text.rstrip(" ?!.…~")
    for ending in sorted(_CASUAL_ENDINGS, key=len, reverse=True):
        if stripped.endswith(ending):
            return ending
    return ""


def static_context_for(gallery_id: str) -> dict:
    """Return legacy style context or an inferred display identity.

    New boards should not be added here as exact hardcoded prompt contexts.
    Exact contexts are kept only for older installations, while newly inferred
    boards get their display name from gallery_purposes.json token matching.
    """

    ctx_db = pm.load_json("gallery_contexts.json")
    if not isinstance(ctx_db, dict):
        return {}

    gallery_id = str(gallery_id or "").strip()
    if not gallery_id:
        ctx = ctx_db.get("default", {})
        return ctx if isinstance(ctx, dict) else {}

    ctx = ctx_db.get(gallery_id)
    if ctx is None:
        for key, value in ctx_db.items():
            key_text = str(key)
            if key_text.startswith("_") or key_text == "default":
                continue
            if key_text and (key_text in gallery_id or gallery_id in key_text):
                ctx = value
                break
    if ctx is None:
        identity = gallery_purpose.identity_metadata(gallery_id)
        if identity:
            return {
                "gallery_name": identity.get("gallery_name")
                or identity.get("topic_label")
                or gallery_id,
                "typical_nickname": "ㅇㅇ",
                "grammar_rules": [],
                "fewshot": [],
            }
    if ctx is None:
        ctx = ctx_db.get("default", {})
    return ctx if isinstance(ctx, dict) else {}


def build_style_profile(
    raw_data: dict | None = None,
    *,
    gallery_id: str = "",
    titles: Iterable[object] | None = None,
    comments: Iterable[object] | None = None,
) -> dict:
    """Build a compact style profile from current board text.

    The profile intentionally stores ratios and high-level instructions, not
    sensitive source text. It is safe to pass through app state and prompts.
    """

    raw_data = raw_data or {}
    source_titles = _compact_texts(titles if titles is not None else raw_data.get("titles", []))
    source_comments = _compact_texts(
        comments if comments is not None else raw_data.get("comments", []),
        limit=120,
    )
    texts = source_titles + source_comments
    total = len(texts)

    laugh_count = sum(1 for text in texts if _LAUGH_RE.search(text))
    long_laugh_count = sum(1 for text in texts if re.search(r"[ㅋㅎ]{5,}", text))
    shortener_count = sum(1 for text in texts if _SHORTENER_RE.search(text))
    arrow_count = sum(1 for text in texts if any(marker in text for marker in _ARROW_MARKERS))
    question_count = sum(
        1
        for text in texts
        if _QUESTION_ENDING_RE.search(text.rstrip(" ?!.…~ㅋㅋㅎㅎ"))
        or text.rstrip().endswith("?")
    )
    avg_title_len = round(sum(len(text) for text in source_titles) / len(source_titles), 1) if source_titles else 0.0
    ending_counts = Counter(_ending(text) for text in source_titles)
    ending_counts.pop("", None)

    resolved_gallery_id = str(gallery_id or raw_data.get("gallery_id", "") or "").strip()
    static_ctx = static_context_for(resolved_gallery_id)
    gallery_name = str(static_ctx.get("gallery_name") or "").strip()
    if gallery_name in {"", "갤러리", "게시판"}:
        identity = gallery_purpose.identity_metadata(resolved_gallery_id)
        gallery_name = str(
            identity.get("gallery_name")
            or identity.get("topic_label")
            or resolved_gallery_id
            or "게시판"
        ).strip()

    allow_long_laugh = _ratio(long_laugh_count, total) >= 0.08 or _ratio(laugh_count, total) >= 0.22
    profile = {
        "gallery_id": resolved_gallery_id,
        "gallery_name": gallery_name,
        "sample_size": total,
        "avg_title_len": avg_title_len,
        "laugh_ratio": _ratio(laugh_count, total),
        "long_laugh_ratio": _ratio(long_laugh_count, total),
        "shortener_ratio": _ratio(shortener_count, total),
        "arrow_ratio": _ratio(arrow_count, total),
        "question_ratio": _ratio(question_count, total),
        "common_endings": [ending for ending, _ in ending_counts.most_common(4)],
        "allow_long_laugh": allow_long_laugh,
        "rules": style_rules_from_profile(
            {
                "sample_size": total,
                "avg_title_len": avg_title_len,
                "laugh_ratio": _ratio(laugh_count, total),
                "long_laugh_ratio": _ratio(long_laugh_count, total),
                "shortener_ratio": _ratio(shortener_count, total),
                "arrow_ratio": _ratio(arrow_count, total),
                "question_ratio": _ratio(question_count, total),
                "common_endings": [ending for ending, _ in ending_counts.most_common(4)],
                "allow_long_laugh": allow_long_laugh,
            }
        ),
    }
    return profile


def style_rules_from_profile(profile: dict) -> list[str]:
    """Translate numeric style signals into generation rules."""

    rules: list[str] = []
    sample_size = int(profile.get("sample_size", 0) or 0)
    if sample_size <= 0:
        return rules

    avg_title_len = float(profile.get("avg_title_len", 0.0) or 0.0)
    laugh_ratio = float(profile.get("laugh_ratio", 0.0) or 0.0)
    long_laugh_ratio = float(profile.get("long_laugh_ratio", 0.0) or 0.0)
    shortener_ratio = float(profile.get("shortener_ratio", 0.0) or 0.0)
    arrow_ratio = float(profile.get("arrow_ratio", 0.0) or 0.0)
    question_ratio = float(profile.get("question_ratio", 0.0) or 0.0)
    common_endings = [str(item) for item in profile.get("common_endings", []) if str(item).strip()]

    if avg_title_len and avg_title_len <= 24:
        rules.append("제목은 짧게 둔다. 긴 문장형 설명 제목보다 한 줄 반응에 가깝게 쓴다.")
        rules.append("제목이 이미 반응을 담으면 본문은 비우거나 35자 안팎의 한 줄만 보탠다.")
    elif avg_title_len >= 36:
        rules.append("제목이 다소 길어도 되지만, 본문까지 설명문처럼 늘리지 않는다.")

    if laugh_ratio >= 0.18:
        if long_laugh_ratio >= 0.08:
            rules.append("이 갤러리는 웃음 꼬리를 길게 붙이는 편이다. 자연스러운 글에는 ㅋㅋㅋㅋ 정도를 가끔 허용한다.")
        else:
            rules.append("웃음 표지는 짧게 쓴다. ㅋㅋ 또는 ㅋㅋㅋ 정도만 가끔 붙인다.")
    else:
        rules.append("웃음 표지는 기본적으로 아낀다. 필요할 때만 짧게 붙인다.")

    if shortener_ratio >= 0.08:
        rules.append("ㄹㅇ, ㅇㅇ, ㄷㄷ 같은 줄임 반응을 글마다 하나 이하로 자연스럽게 섞을 수 있다.")
    else:
        rules.append("줄임말은 과하게 넣지 않는다.")

    if arrow_ratio >= 0.04:
        rules.append("'대상 << 반응' 또는 '대상 <- 이유' 같은 지목형 제목을 일부 wave에만 쓴다.")

    if question_ratio >= 0.34:
        rules.append("질문형을 쓸 수 있지만 단어 뜻 질문이 아니라 이미 아는 사람이 한 지점만 확인하는 말투로 쓴다.")

    if common_endings:
        rules.append(f"말끝은 최근 제목에서 자주 보인 {', '.join(common_endings[:3])} 계열을 참고하되 반복하지 않는다.")

    return rules[:6]


def prompt_block(profile: dict | None) -> str:
    """Render the profile as a compact prompt block."""

    if not isinstance(profile, dict) or not profile.get("rules"):
        return ""
    lines = [
        f"[갤러리별 문체 프로필 — {profile.get('gallery_name') or profile.get('gallery_id') or '게시판'}]",
        (
            "- 신호: "
            f"웃음 {profile.get('laugh_ratio', 0):.0%}, "
            f"긴 웃음 {profile.get('long_laugh_ratio', 0):.0%}, "
            f"줄임말 {profile.get('shortener_ratio', 0):.0%}, "
            f"평균 제목 {profile.get('avg_title_len', 0)}자"
        ),
    ]
    lines.extend(f"- {rule}" for rule in profile.get("rules", []) if str(rule).strip())
    lines.append("- 이 프로필은 말투 표면만 맞추는 용도다. 금지 표현·민감 주제 안전 규칙보다 우선하지 않는다.")
    return "\n".join(lines)
