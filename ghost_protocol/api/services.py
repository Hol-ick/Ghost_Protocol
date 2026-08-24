"""Service layer behind the Ghost Protocol API facade."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import parse_qs, urlparse

from ghost_protocol import __version__, database, prompt_manager as pm
from ghost_protocol.api import API_VERSION
from ghost_protocol.api.schemas import (
    CommunityAnalyzeRequest,
    CommunityScanRequest,
    CommunitySignalResponse,
    CommunitySnapshotResponse,
    DraftLength,
    HealthResponse,
    LocalOverviewResponse,
    PostDraftRequest,
    PostDraftResponse,
    ReplyDraftRequest,
    ReplyDraftResponse,
    SafetyContract,
    ThreadAnalysisResponse,
    ThreadAnalyzeRequest,
)
from ghost_protocol.content_filter import (
    classify_noise_text,
    sensitive_generation_violations,
)
from ghost_protocol.scraper import TrendScraper


_TOKEN_RE = re.compile(r"[A-Za-z0-9\uac00-\ud7a3]{2,}")
_STOPWORDS = {
    "the",
    "and",
    "for",
    "this",
    "that",
    "\uc774\uac70",
    "\uadf8\uac70",
    "\uc9c4\uc9dc",
    "\uadf8\ub0e5",
    "\uac8c\uc2dc\uae00",
    "\ub313\uae00",
}

_SUPPORT_TERMS = (
    "agree",
    "true",
    "correct",
    "\ub9de",
    "\uc778\uc815",
    "\ub3d9\uc758",
)
_REBUTTAL_TERMS = (
    "but",
    "however",
    "wrong",
    "evidence",
    "source",
    "\uc544\ub2d8",
    "\uc544\ub2c8",
    "\uadfc\ub370",
    "\ud558\uc9c0\ub9cc",
    "\ud2c0",
    "\ubc18\ubc15",
    "\uadfc\uac70",
)
_QUESTION_TERMS = ("?", "\uc65c", "\ubb50", "\uc5b4\ub5bb\uac8c")
_HOSTILE_TERMS = (
    "idiot",
    "stupid",
    "\ubcd1\uc2e0",
    "\ubc14\ubcf4",
    "\uaebc\uc838",
    "\uc9c0\ub784",
)


def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_version=__version__,
        api_version=API_VERSION,
    )


def safety_contract() -> SafetyContract:
    return SafetyContract()


def collect_community_snapshot(
    request: CommunityScanRequest,
    *,
    progress_callback: Any | None = None,
) -> CommunitySnapshotResponse:
    scraper = TrendScraper()
    raw = scraper.collect_trending(
        gallery_id=request.community_id,
        gallery_type=request.community_type,
        pages=request.pages,
        max_comments_per_post=request.max_comments_per_post,
        top_posts_per_page=request.top_posts_per_page,
        source_detail_limit=request.source_detail_limit,
        source_comments_per_post=request.source_comments_per_post,
        progress_callback=progress_callback,
    )
    return _snapshot_response(raw, source=request.source)


def analyze_community_signal(request: CommunityAnalyzeRequest) -> CommunitySignalResponse:
    raw = dict(request.snapshot or {})
    if not raw:
        raw = collect_community_snapshot(request).model_dump(exclude={"safety"})
        raw["gallery_id"] = raw.pop("community_id", request.community_id)
        raw["gallery_type"] = raw.pop("community_type", request.community_type)

    if request.use_llm:
        from ghost_protocol.brain import GhostBrain

        analysis = GhostBrain(api_key=request.api_key).analyze_trend(raw, top_k=request.top_k)
    else:
        analysis = build_keyword_signal(raw, top_k=request.top_k)

    return CommunitySignalResponse(
        source=request.source,
        community_id=str(raw.get("gallery_id") or request.community_id),
        community_type=str(raw.get("gallery_type") or request.community_type),
        analysis=analysis,
        snapshot_stats=_snapshot_stats(raw),
    )


def get_local_overview(community_id: str, *, limit: int = 20) -> LocalOverviewResponse:
    database.init_db()
    posts = database.get_all_posts(community_id)
    comments = database.get_all_comments(community_id)
    top_keywords = _top_keywords(
        [str(row.get("title", "")) for row in posts]
        + [str(row.get("content", "")) for row in comments],
        top_k=20,
    )
    return LocalOverviewResponse(
        community_id=community_id,
        post_count=database.get_post_count(community_id),
        comment_count=database.get_comment_count(community_id),
        ai_post_count=database.get_ai_post_count(community_id),
        top_keywords=top_keywords,
        recent_posts=[dict(row) for row in posts[: max(1, limit)]],
    )


def build_post_draft(request: PostDraftRequest) -> PostDraftResponse:
    if not request.api_key:
        raise ValueError("api_key is required for LLM draft generation")

    from ghost_protocol.brain import GhostBrain

    length_label = _length_label(request.length)
    result = GhostBrain(api_key=request.api_key).generate_post(
        topic=request.topic,
        gallery_id=request.community_id or "default",
        tone=_tone_label(request.tone),
        context_hours=request.context_hours or None,
        length=length_label,
        keywords=request.keywords,
        recent_posts=None,
    )
    title = str(result.get("title", "")).strip()
    content = str(result.get("content", "")).strip()
    violations = sensitive_generation_violations(
        f"{title}\n{content}",
        topic=request.topic,
    )
    if result.get("_parse_error"):
        violations.append("parse_error")
    return PostDraftResponse(
        title=title,
        content=content,
        risk_flags=list(dict.fromkeys(violations)),
        raw_model_metadata={
            key: value
            for key, value in result.items()
            if key.startswith("_") and key != "_raw_response"
        },
    )


def analyze_thread(request: ThreadAnalyzeRequest) -> ThreadAnalysisResponse:
    payload = _thread_payload(request)
    title = str(payload.get("title") or payload.get("source_title") or request.title or "").strip()
    content = str(payload.get("content") or request.content or "").strip()
    comments = [
        str(item).strip()
        for item in (payload.get("comments") or request.comments or [])
        if str(item).strip()
    ]

    claims = _extract_claims(title, content)
    clusters = _cluster_comments(comments)
    counterpoints = _counterpoints(comments)
    source_text = "\n".join([title, content, *comments[:20]])
    risk_flags = _risk_flags(source_text)

    return ThreadAnalysisResponse(
        source=request.source,
        community_id=str(payload.get("community_id") or request.community_id or ""),
        community_type=str(payload.get("community_type") or request.community_type),
        post_no=str(payload.get("post_no") or request.post_no or ""),
        post_url=str(payload.get("url") or request.post_url or ""),
        title=title,
        content_excerpt=content[:600],
        post_summary=_summarize_post(title, content),
        main_claims=claims,
        comment_clusters=clusters,
        key_counterpoints=counterpoints,
        risk_flags=risk_flags,
        fetched_live=bool(payload.get("fetched_live")),
    )


def build_reply_draft(request: ReplyDraftRequest) -> ReplyDraftResponse:
    analysis = request.analysis or analyze_thread(request.thread)  # type: ignore[arg-type]
    counterpoints = analysis.key_counterpoints[:2]
    draft = _compose_reply(
        analysis,
        intent=request.intent,
        tone=request.tone,
        length=request.length,
        must_include_evidence=request.must_include_evidence,
    )
    risk_flags = _risk_flags(draft)
    return ReplyDraftResponse(
        draft=draft,
        intent=request.intent,
        tone=request.tone,
        length=request.length,
        used_counterpoints=counterpoints,
        risk_flags=risk_flags,
    )


def build_keyword_signal(raw: dict[str, Any], *, top_k: int = 30) -> dict[str, Any]:
    titles = [str(item) for item in raw.get("titles", [])]
    comments = [str(item) for item in raw.get("comments", [])]
    keywords = _top_keywords(titles + comments, top_k=top_k)
    return {
        "hot_topics": keywords[:5],
        "sentiment": "unclassified",
        "memes": [],
        "summary": _keyword_summary(keywords),
        "ai_analysis": "Keyword-only analysis. Enable use_llm for a richer brief.",
        "generation_guidance": (
            "Use the detected topics as context for a reviewed, non-automated draft."
        ),
        "top_keywords": keywords,
        "stats": _snapshot_stats(raw),
    }


def _snapshot_response(raw: dict[str, Any], *, source: str) -> CommunitySnapshotResponse:
    return CommunitySnapshotResponse(
        source=source,
        community_id=str(raw.get("gallery_id") or ""),
        community_type=str(raw.get("gallery_type") or "mgallery"),
        collected_at=str(raw.get("collected_at") or ""),
        titles=[str(item) for item in raw.get("titles", [])],
        comments=[str(item) for item in raw.get("comments", [])],
        authors=[str(item) for item in raw.get("authors", [])],
        raw_posts=[dict(item) for item in raw.get("raw_posts", []) if isinstance(item, dict)],
        stats=_snapshot_stats(raw),
        noise_filter=dict(raw.get("noise_filter") or {}),
        posting_rhythm=dict(raw.get("posting_rhythm") or {}),
    )


def _snapshot_stats(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "title_count": len(raw.get("titles") or []),
        "comment_count": len(raw.get("comments") or []),
        "author_count": len(raw.get("authors") or []),
        "raw_post_count": len(raw.get("raw_posts") or []),
        "ai_post_count": int(raw.get("ai_post_count") or 0),
        "total_post_count": int(raw.get("total_post_count") or 0),
        "collected_at": raw.get("collected_at", ""),
    }


def _top_keywords(items: list[str], *, top_k: int = 30) -> list[str]:
    tokens: list[str] = []
    for item in items:
        tokens.extend(
            token.casefold()
            for token in _TOKEN_RE.findall(str(item))
            if token.casefold() not in _STOPWORDS
        )
    return [token for token, _ in Counter(tokens).most_common(top_k)]


def _keyword_summary(keywords: list[str]) -> str:
    if not keywords:
        return "No strong keyword signal was detected."
    return "Top discussion signals: " + ", ".join(keywords[:5])


def _thread_payload(request: ThreadAnalyzeRequest) -> dict[str, Any]:
    payload = {
        "community_id": request.community_id or "",
        "community_type": request.community_type,
        "post_no": request.post_no or "",
        "url": request.post_url or "",
        "title": request.title,
        "content": request.content,
        "comments": request.comments,
        "fetched_live": False,
    }
    if request.post_url:
        parsed = _parse_dcinside_url(request.post_url)
        payload.update({key: value for key, value in parsed.items() if value})

    if (
        request.fetch_live
        and payload.get("community_id")
        and payload.get("post_no")
        and (not request.title or not request.content)
    ):
        scraper = TrendScraper()
        snapshot = scraper.fetch_post_snapshot(
            str(payload["community_id"]),
            str(payload["post_no"]),
            str(payload.get("community_type") or "mgallery"),
        )
        if snapshot:
            payload.update(snapshot)
            payload["fetched_live"] = True
        if not payload.get("comments"):
            payload["comments"] = scraper.fetch_comments_ajax(
                str(payload["community_id"]),
                str(payload["post_no"]),
                str(payload.get("community_type") or "mgallery"),
                e_s_n_o=str(payload.get("e_s_n_o") or ""),
            )
    return payload


def _parse_dcinside_url(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    gallery_type = "mgallery"
    if "/mini/" in parsed.path:
        gallery_type = "mini"
    elif "/board/" in parsed.path and "/mgallery/" not in parsed.path:
        gallery_type = "board"
    return {
        "community_id": (query.get("id") or [""])[0],
        "post_no": (query.get("no") or [""])[0],
        "community_type": gallery_type,
        "url": url,
    }


def _extract_claims(title: str, content: str) -> list[str]:
    pieces = [title.strip()]
    pieces.extend(
        part.strip()
        for part in re.split(r"[\n.!?\u3002]+", content)
        if part.strip()
    )
    claims: list[str] = []
    for piece in pieces:
        compact = " ".join(piece.split())
        if compact and compact not in claims:
            claims.append(compact[:180])
        if len(claims) >= 4:
            break
    return claims


def _summarize_post(title: str, content: str) -> str:
    claims = _extract_claims(title, content)
    if not claims:
        return "No readable post body was provided."
    return " / ".join(claims[:2])


def _cluster_comments(comments: list[str]) -> list[dict[str, Any]]:
    buckets: dict[str, list[str]] = {
        "support": [],
        "rebuttal": [],
        "question": [],
        "hostile": [],
        "other": [],
    }
    for comment in comments:
        label = _comment_label(comment)
        buckets[label].append(comment)
    return [
        {"label": label, "count": len(items), "samples": items[:3]}
        for label, items in buckets.items()
        if items
    ]


def _comment_label(comment: str) -> str:
    text = comment.casefold()
    if any(term in text for term in _HOSTILE_TERMS):
        return "hostile"
    if any(term in text for term in _REBUTTAL_TERMS):
        return "rebuttal"
    if any(term in text for term in _QUESTION_TERMS):
        return "question"
    if any(term in text for term in _SUPPORT_TERMS):
        return "support"
    return "other"


def _counterpoints(comments: list[str]) -> list[str]:
    selected = [
        " ".join(comment.split())[:220]
        for comment in comments
        if _comment_label(comment) in {"rebuttal", "question"}
    ]
    return list(dict.fromkeys(selected))[:5]


def _risk_flags(text: str) -> list[str]:
    flags: list[str] = []
    if classify_noise_text(text).is_noise:
        flags.append("noise_or_promo_like")
    flags.extend(sensitive_generation_violations(text, topic=text))
    return list(dict.fromkeys(flags))


def _compose_reply(
    analysis: ThreadAnalysisResponse,
    *,
    intent: str,
    tone: str,
    length: str,
    must_include_evidence: bool,
) -> str:
    claim = analysis.main_claims[0] if analysis.main_claims else analysis.title
    counterpoint = analysis.key_counterpoints[0] if analysis.key_counterpoints else ""
    if intent == "logical_rebuttal":
        base = (
            "\uc8fc\uc7a5\uc758 \ubc29\ud5a5\uc740 \uc774\ud574\ub418\uc9c0\ub9cc, "
            "\uadf8 \uacb0\ub860\uc744 \ub2e8\uc815\ud558\uae30\uc5d0\ub294 \uadfc\uac70\uac00 \uc870\uae08 \ubd80\uc871\ud574 \ubcf4\uc785\ub2c8\ub2e4."
        )
        if counterpoint:
            base += (
                " \ub313\uae00\uc5d0\uc11c\ub3c4 \uc9c0\uc801\ub41c \uc810\ucc98\ub7fc "
                f"'{counterpoint}' \ubd80\ubd84\uc744 \uba3c\uc800 \ud655\uc778\ud574\uc57c \ud569\ub2c8\ub2e4."
            )
    elif intent == "clarification":
        base = (
            "\uc9c0\uae08 \uae00\uc5d0\uc11c \ud655\uc2e4\ud55c \ubd80\ubd84\uacfc \ucd94\uc815\uc778 \ubd80\ubd84\uc744 "
            "\ub098\ub220\uc11c \ubcf4\uba74 \ub354 \uc88b\uc744 \uac83 \uac19\uc2b5\ub2c8\ub2e4."
        )
    elif intent == "question_answer":
        base = (
            "\uc9c8\ubb38\uc758 \ud575\uc2ec\uc740 \uc774 \uc8fc\uc7a5\uc774 \uc2e4\uc81c \uadfc\uac70\ub85c "
            "\uc9c0\uc9c0\ub418\ub294\uc9c0\uc778\ub370, \ud604\uc7ac \uae00\ub9cc\uc73c\ub85c\ub294 \ub2e8\uc815\ud558\uae30 \uc5b4\ub835\uc2b5\ub2c8\ub2e4."
        )
    else:
        base = (
            "\ud575\uc2ec\uc740 "
            f"'{claim}' \ubd80\ubd84\uc778\ub370, \uc774\uac74 \ucd94\uac00 \uadfc\uac70\uc640 \ub9e5\ub77d\uc744 \uac19\uc774 \ubd10\uc57c \ud569\ub2c8\ub2e4."
        )

    if must_include_evidence:
        base += (
            " \ucd5c\uc18c\ud55c \uc218\uce58, \uc6d0\ubb38, \uc2dc\uc810\uc744 \uac19\uc774 \uc81c\uc2dc\ud574\uc57c "
            "\ubc18\ubc15\uc774\ub098 \ub3d9\uc758\uac00 \ub354 \ubd84\uba85\ud574\uc9d1\ub2c8\ub2e4."
        )
    if tone == "firm":
        base = base.replace("\uc88b\uc744 \uac83 \uac19\uc2b5\ub2c8\ub2e4", "\ud544\uc694\uac00 \uc788\uc2b5\ub2c8\ub2e4")
    if tone == "concise" or length == "short":
        sentences = re.split(r"(?<=[.!?\ub2e4])\s+", base)
        return " ".join(sentences[:2]).strip()
    if length == "long":
        base += (
            " \uac10\uc815\uc801 \ud45c\ud604\ubcf4\ub2e4\ub294 \uc0ac\uc2e4 \uad00\uacc4\ub97c \uc815\ub9ac\ud558\uba74 "
            "\ub17c\uc810\uc774 \ud6e8\uc52c \uae54\ub054\ud574\uc9c8 \uac83 \uac19\uc2b5\ub2c8\ub2e4."
        )
    return base


def _tone_label(tone: str) -> str:
    if tone == "firm":
        return "analytical"
    if tone == "concise":
        return "neutral"
    return "neutral"


def _length_label(length: DraftLength) -> str:
    labels = list(pm.load_json("lengths.json").keys())
    if not labels:
        return ""
    if length == "short":
        return labels[min(1, len(labels) - 1)]
    if length == "long":
        return labels[-1]
    return labels[min(2, len(labels) - 1)]
