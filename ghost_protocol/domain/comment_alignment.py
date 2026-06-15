"""Topic alignment helpers for draft-attached comments.

The generator can pick a real board comment as a companion reply. A loose
"same source post" match is not enough: source posts often contain mixed
threads, and a concrete off-topic comment makes the generated draft look
stitched together. Keep this module dependency-free so it can be tested without
Streamlit or browser automation.
"""

from __future__ import annotations

import re


_TOKEN_RE = re.compile(r"[0-9a-zA-Z가-힣]{2,}")

_STOPWORDS = {
    "그냥",
    "진짜",
    "근데",
    "아니",
    "이거",
    "저거",
    "그거",
    "뭔가",
    "너무",
    "되게",
    "계속",
    "같음",
    "같다",
    "같네",
    "아님",
    "아닌",
    "하는",
    "하고",
    "해서",
    "보면",
    "보니까",
    "오늘",
    "요즘",
    "제목",
    "본문",
    "댓글",
    "갤러리",
    "게시판",
}

_GENERIC_REACTION_TOKENS = {
    "ㄹㅇ",
    "ㅇㅇ",
    "ㅋㅋ",
    "ㅋㅋㅋ",
    "ㅎㅎ",
    "ㄷㄷ",
    "맞음",
    "맞네",
    "그러게",
    "그렇긴",
    "인정",
    "공감",
    "웃기네",
    "신기하네",
    "애매하네",
    "개웃기네",
    "그럴듯",
}


def topic_tokens(text: object) -> set[str]:
    """Return concrete-ish tokens suitable for coarse topic overlap checks."""

    raw = str(text or "").lower()
    tokens: set[str] = set()
    for token in _TOKEN_RE.findall(raw):
        if token.isdigit() or token in _STOPWORDS:
            continue
        if set(token) <= {"ㅋ", "ㅎ", "ㅠ", "ㅜ"}:
            continue
        tokens.add(token)
    return tokens


def is_generic_reaction(text: object) -> bool:
    """Return True for short replies that can attach to many nearby posts."""

    raw = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not raw:
        return False
    if len(raw) <= 18 and re.fullmatch(r"[ㅋㅎㅠㅜㄷㅇ\s.!?]+", raw):
        return True
    tokens = topic_tokens(raw)
    if len(raw) <= 40 and (not tokens or tokens <= _GENERIC_REACTION_TOKENS):
        return True
    return False


def comment_fits_draft(
    comment: object,
    *,
    title: object,
    content: object = "",
    target_title: object = "",
    target_content: object = "",
) -> bool:
    """Return whether a source comment can naturally accompany a draft.

    Concrete comments must share a token with the generated draft. Very short
    generic reactions are allowed only when the draft clearly matches the
    source post, so unrelated one-liners do not drift into the next cycle.
    """

    draft_tokens = topic_tokens(f"{title or ''} {content or ''}")
    if not draft_tokens:
        return is_generic_reaction(comment)

    comment_tokens = topic_tokens(comment)
    if comment_tokens & draft_tokens:
        return True

    source_tokens = topic_tokens(f"{target_title or ''} {target_content or ''}")
    if is_generic_reaction(comment) and source_tokens & draft_tokens:
        return True

    return False
