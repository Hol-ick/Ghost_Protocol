"""Pure view-model helpers for the Intel dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


SENTIMENT_CLASSES: tuple[tuple[str, str], ...] = (
    ("패닉", "panic"),
    ("공포", "panic"),
    ("적대적", "hostile"),
    ("분노", "hostile"),
    ("공격", "hostile"),
    ("조롱", "mock"),
    ("냉소", "mock"),
    ("비꼬", "mock"),
    ("우호적", "friendly"),
    ("긍정", "friendly"),
)


@dataclass(frozen=True)
class AiOccupationView:
    ai_count: int
    total_count: int
    human_count: int
    ai_pct: float
    human_pct: float
    bar_width: str
    pct_label: str
    ratio_label: str
    bar_color: str
    pct_color: str


def sentiment_css_class(sentiment: str) -> str:
    """Map an Intel sentiment label to the dashboard CSS class."""
    raw = str(sentiment or "")
    for keyword, class_name in SENTIMENT_CLASSES:
        if keyword in raw:
            return f"intel-sentiment-{class_name}"
    return "intel-sentiment-neutral"


def build_ai_occupation_view(
    raw_posts: Iterable[dict] | None,
    stats: dict | None,
    ai_post_nos: Iterable[str] | None,
) -> AiOccupationView:
    """Build the bot/human occupation metrics shown in the Intel panel."""
    posts = list(raw_posts or [])
    stat_data = stats or {}
    ai_nos = {str(post_no) for post_no in (ai_post_nos or set())}

    ai_count_db = sum(
        1
        for post in posts
        if post.get("is_bot") or str(post.get("post_no", "")) in ai_nos
    )
    ai_count = max(ai_count_db, int(stat_data.get("ai_post_count", 0)))
    total_count = max(len(posts), int(stat_data.get("total_post_count", 0)))
    human_count = max(0, total_count - ai_count)

    if total_count > 0:
        ai_pct = min(100.0, ai_count / total_count * 100)
        human_pct = 100.0 - ai_pct
        bar_width = f"{ai_pct:.1f}%"
        pct_label = f"{ai_pct:.1f}%"
        ratio_label = f"{ai_count} / {total_count}개"
    else:
        ai_pct = 0.0
        human_pct = 100.0
        bar_width = "0%"
        pct_label = "—"
        ratio_label = "데이터 없음"

    bar_color = (
        "linear-gradient(90deg,#FF2020,#FF4B4B)"
        if ai_pct >= 50
        else "linear-gradient(90deg,#FF8C00,#FFBF00)"
        if ai_pct >= 20
        else "linear-gradient(90deg,#00C2A0,#00F0FF)"
    )
    pct_color = "#FF4B4B" if ai_pct >= 50 else "#FFBF00" if ai_pct >= 20 else "#00F0FF"

    return AiOccupationView(
        ai_count=ai_count,
        total_count=total_count,
        human_count=human_count,
        ai_pct=ai_pct,
        human_pct=human_pct,
        bar_width=bar_width,
        pct_label=pct_label,
        ratio_label=ratio_label,
        bar_color=bar_color,
        pct_color=pct_color,
    )


def build_raw_post_debug_rows(
    raw_posts: Iterable[dict] | None,
    ai_post_nos: Iterable[str] | None,
) -> list[dict[str, str]]:
    """Build dataframe rows for the Intel raw-post debug panel."""
    ai_nos = {str(post_no) for post_no in (ai_post_nos or set())}
    rows: list[dict[str, str]] = []
    for post in raw_posts or []:
        post_no = str(post.get("post_no", ""))
        rows.append(
            {
                "글번호": post_no,
                "제목": str(post.get("title", ""))[:45],
                "작성자": str(post.get("author", "")),
                "🤖 봇": "✅ BOT" if post.get("is_bot") or post_no in ai_nos else "—",
            }
        )
    return rows


def raw_post_debug_caption(
    *,
    ai_post_nos_count: int,
    intel_gallery_id: str,
    target_gallery_id: str,
    raw_post_count: int,
) -> str:
    """Build the diagnostic caption for the Intel raw-post debug panel."""
    return (
        f"🔎 진단 | "
        f"DB 봇 post_no 수: **{ai_post_nos_count}개** | "
        f"Intel GID: `{intel_gallery_id}` | "
        f"FIRE GID: `{target_gallery_id}` | "
        f"스캔 글 수: {raw_post_count}개"
    )


def keyword_chart_cache_key(intel_result: dict) -> int:
    """Return the same lightweight key used to cache the Intel keyword chart."""
    return hash(
        str(intel_result.get("top_keywords", []))
        + str(intel_result.get("keyword_counts", {}))
    )
