"""UI formatting helpers for the Streamlit dashboard."""

from __future__ import annotations

import html
import re
import time
from pathlib import Path

import plotly.graph_objects as go

from ghost_protocol import cycle_memory
from ghost_protocol.application import intel_result
from ghost_protocol.domain import board_rhythm
from ghost_protocol.domain import gallery_style
from ghost_protocol.domain import writing_enrichment
from ghost_protocol.ui.intel_view_model import AiOccupationView


def _comment_target_label(target: dict) -> str:
    """Format a comment target for review/copy output."""

    post_no = target.get("post_no", "?")
    label = f"#{post_no}"
    if target.get("simulation_only") or target.get("is_ai_post"):
        label += " (리허설)"
    return label


def _friendly_log_line(line: object) -> str:
    """Convert worker-oriented log tokens into operator-facing wording."""
    text = str(line)
    replacements = (
        ("INFINITE SWARM HALTED", "자동 반복 중단"),
        ("EXECUTION COMPLETE", "발행 완료"),
        ("SWARM COMPLETE", "발행 완료"),
        ("WAVES FIRED", "개 발행"),
        ("WAVES", "개"),
        ("WAVE", "회차"),
        ("SWARM", "실행"),
        ("BATCH", "원고"),
        ("FIRE", "발행"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def render_terminal(logs: list, height_px: int = 400) -> str:
    """Render log lines as a compact terminal panel."""
    parts = []
    for line in reversed(logs[-200:]):
        display_line = _friendly_log_line(line)
        escaped = html.escape(display_line)
        if any(k in str(line) for k in ("WAVE", "SWARM", "BATCH")):
            parts.append(f'<div><span class="t-wave">{escaped}</span></div>')
        elif any(k in str(line) for k in ("COMPLETE", "OK", "SUCCESS", "DONE")):
            parts.append(f'<div><span class="t-ok">{escaped}</span></div>')
        elif any(k in str(line) for k in ("ERROR", "FAIL", "[ERROR]")):
            parts.append(f'<div><span class="t-err">{escaped}</span></div>')
        elif any(k in str(line) for k in ("WARN", "WAIT", "COOLDOWN", "RETRY")):
            parts.append(f'<div><span class="t-warn">{escaped}</span></div>')
        else:
            parts.append(f'<div>{escaped}</div>')

    body = "\n".join(parts) if parts else (
        '<div style="color:#6B7280;font-style:italic">// 작업 대기 중...</div>'
    )
    return f'<div class="terminal" style="height:{height_px}px;">{body}</div>'


def render_idle_terminal(
    *,
    height_px: int,
    lines: list[str] | tuple[str, ...],
) -> str:
    """Render an idle terminal placeholder."""
    body = "<br>".join(html.escape(str(line)) for line in lines)
    return (
        f'<div class="terminal" style="height:{height_px}px">'
        f'<div style="color:#30363D;font-style:italic">'
        f'{body}'
        f'</div></div>'
    )


def render_swarm_preview_card(*, title: str, content: str, wave_label: str) -> str:
    """Render the live Swarm post preview card."""
    return (
        f'<div class="preview-dark">'
        f'<div class="pd-label">{html.escape(wave_label)}</div>'
        f'<div class="pd-title">{html.escape(title)}</div>'
        f'<div class="pd-body">{html.escape(content)}</div>'
        f'</div>'
    )


def render_swarm_empty_preview() -> str:
    """Render the empty Swarm preview placeholder."""
    return (
        '<div class="preview-dark">'
        '<div class="pd-empty">아직 만든 원고가 없습니다.<br><br>'
        '상단에서 주제를 입력한 뒤<br>검토용 원고를 만들어주세요.</div>'
        '</div>'
    )


def render_mission_stat_pill(*, css_class: str, value: object, label: str) -> str:
    """Render a small mission-stat pill."""
    safe_class = html.escape(str(css_class), quote=True)
    return (
        f'<div class="ms-pill {safe_class}">'
        f'<div class="ms-val">{html.escape(str(value))}</div>'
        f'<div class="ms-lbl">{html.escape(label)}</div></div>'
    )


def format_test_log_caption(log_path: str | Path, wave_count: int) -> str:
    """Format the test-summary log path caption."""
    return f"📁 로그 파일: `logs/{Path(log_path).name}`  ({wave_count}회)"


def format_log_copy_text(logs: list, *, limit: int = 200) -> str:
    """Format recent log lines for copy-friendly display."""
    return "\n".join(str(line) for line in logs[-limit:])


def format_activity_log_markdown(
    logs: list,
    *,
    title: str = "실행 로그",
    limit: int = 300,
) -> str:
    """Format recent activity lines as a Markdown block for one-click copying."""

    recent = [str(line) for line in list(logs or [])[-limit:]]
    lines = [
        f"# {title}",
        "",
        f"- 복사 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 로그 줄 수: {len(recent)}개",
        "",
        "```text",
    ]
    lines.extend(recent)
    lines.append("```")
    return "\n".join(lines).strip()


def format_scripts_for_copy(scripts: list[dict]) -> str:
    """Convert generated script payloads into a readable plain-text bundle."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    valid_scripts = [item for item in scripts if not item.get("_failed")]
    failed_count = len(scripts) - len(valid_scripts)
    count_line = f"총 {len(valid_scripts)}개 원고"
    if failed_count:
        count_line += f" (요청 {len(scripts)}개 · 실패 {failed_count}개 제외)"
    lines = [
        "=" * 60,
        "GHOST PROTOCOL — 검토용 원고 모음",
        f"생성 시각: {ts}",
        count_line,
        "=" * 60,
    ]
    for item in valid_scripts:
        lines.append("")
        wave = item.get("wave", "?")
        persona = item.get("persona_name", "")
        tone_key = item.get("tone", "")
        lines.append(f"원고 {wave} [{persona} / {tone_key}]")
        lines.append(f"  제목: {item.get('title', '')}")
        for i, content_line in enumerate(item.get("content", "").splitlines()):
            prefix = "  본문: " if i == 0 else "        "
            lines.append(f"{prefix}{content_line}")
        for target in item.get("target_comments", []):
            lines.append(
                "  댓글 "
                f"{_comment_target_label(target)}: {target.get('comment', '')}"
            )
        lines.append("-" * 40)
    return "\n".join(lines)


def format_scripts_markdown(scripts: list[dict]) -> str:
    """Convert generated script payloads into a Markdown review bundle."""

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    valid_scripts = [item for item in scripts if not item.get("_failed")]
    failed_scripts = [item for item in scripts if item.get("_failed")]
    lines = [
        "# 검토용 원고 모음",
        "",
        f"- 생성 시각: {ts}",
        f"- 요청 원고: {len(scripts)}개",
        f"- 생성 성공: {len(valid_scripts)}개",
        f"- 생성 실패: {len(failed_scripts)}개",
    ]
    for item in valid_scripts:
        wave = item.get("wave", "?")
        persona = item.get("persona_name", "")
        tone_key = item.get("tone", "")
        lines.extend([
            "",
            f"## 원고 {wave} — {persona} / `{tone_key}`",
        ])
        lines.extend([
            f"- 제목: {item.get('title', '')}",
            "",
            "```text",
            str(item.get("content", "")).strip(),
            "```",
        ])
        comments = item.get("target_comments", [])
        if comments:
            lines.extend(["", "### 댓글 초안"])
            for target in comments:
                lines.append(
                    f"- {_comment_target_label(target)}: {target.get('comment', '')}"
                )

    if failed_scripts:
        lines.extend([
            "",
            "# 생성 실패 원고",
            "",
            "마지막 생성 후보와 검증 실패 사유입니다.",
        ])
        for item in failed_scripts:
            wave = item.get("wave", "?")
            persona = item.get("persona_name", "")
            tone_key = item.get("tone", "")
            rejected_title = str(item.get("_rejected_title") or "").strip()
            rejected_content = str(item.get("_rejected_content") or "").strip()
            reason = str(
                item.get("_failure_reason") or "검증을 통과하지 못했습니다."
            ).strip()
            stage = str(item.get("_failure_stage") or "").strip()
            detail = str(item.get("_failure_detail") or "").strip()
            attempts = int(item.get("_failure_attempts") or 0)
            has_candidate = bool(rejected_title or rejected_content)
            lines.extend([
                "",
                f"## 원고 {wave} — {persona} / `{tone_key}`",
                (
                    f"- 후보 제목: {rejected_title}"
                    if rejected_title
                    else "- 후보 제목: (복구 가능한 제목 없음)"
                ),
                "",
                "```text",
                rejected_content or "(복구 가능한 본문 없음)",
                "```",
            ])
            rejected_comments = item.get("_rejected_comments", [])
            if rejected_comments:
                lines.extend(["", "### 댓글 후보"])
                for target in rejected_comments:
                    lines.append(
                        f"- {_comment_target_label(target)}: {target.get('comment', '')}"
                    )
            lines.extend(["", f"- 실패 사유: {reason}"])
            if stage:
                lines.append(f"- 실패 단계: `{stage}`")
            if attempts:
                lines.append(f"- 생성 시도: {attempts}회")
            if detail:
                lines.append(f"- 상세: {detail}")
            elif not has_candidate:
                lines.append(
                    "- 후보 상태: API 응답에 검토 가능한 제목·본문이 없어 "
                    "실패 메타데이터만 보존됨"
                )
    return "\n".join(lines).strip()


def _source_post_title(post: dict) -> str:
    return str(post.get("source_title") or post.get("title") or "").strip()


def _source_post_content(post: dict, *, limit: int) -> str:
    content = " ".join(str(post.get("content") or "").split())
    if not content:
        return "(본문 미수집)"
    if len(content) <= limit:
        return content
    return content[:limit].rstrip() + "..."


def _source_post_comments(post: dict, *, limit: int = 5, comment_limit: int = 240) -> list[str]:
    comments = []
    for value in list(post.get("comments") or [])[:limit]:
        text = " ".join(str(value or "").split())
        if not text:
            continue
        if len(text) > comment_limit:
            text = text[:comment_limit].rstrip() + "..."
        comments.append(text)
    return comments


def _escape_fence(text: str) -> str:
    return text.replace("```", "`\u200b``")


def format_source_posts_markdown(
    raw_posts: list[dict],
    *,
    max_posts: int = 120,
    content_limit: int = 700,
) -> str:
    """Format crawled board titles/body snapshots for downstream review.

    The live UI only shows compact progress logs. This export keeps the source
    material that explains why a generated body feels native or AI-like.
    """

    posts = [post for post in list(raw_posts or []) if isinstance(post, dict)]
    if not posts:
        return ""

    visible = posts[:max_posts]
    body_count = sum(1 for post in visible if str(post.get("content") or "").strip())
    comment_set_count = sum(1 for post in visible if post.get("comments"))
    comment_count = sum(len(list(post.get("comments") or [])) for post in visible)
    rhythm = board_rhythm.analyze_posting_rhythm(visible)
    lines: list[str] = [
        "## 원본 게시글 자료",
        "",
        f"- 포함: 제목 {len(visible)}개 · 본문 {body_count}개 · 댓글 {comment_count}개",
        f"- 댓글 세트: {comment_set_count}개 게시글",
        "- 용도: 생성 원고의 제목/본문/댓글 리듬을 실제 게시판 글과 대조하기 위한 원본 자료",
    ]
    if rhythm.get("interval_count"):
        lines.append(
            "- 글 간격: "
            f"평균 {board_rhythm.format_seconds(rhythm.get('average_seconds'))} · "
            f"중앙 {board_rhythm.format_seconds(rhythm.get('median_seconds'))} · "
            f"추천 발행 {rhythm.get('recommended_minutes')}분"
        )
    lines.extend(["", "### 원본 제목 리스트"])

    for idx, post in enumerate(visible, 1):
        page = post.get("page")
        post_no = post.get("post_no") or post.get("no") or "?"
        title = _source_post_title(post) or "(제목 없음)"
        created_at = str(post.get("created_at") or "").strip()
        prefix = f"{idx}. "
        meta = f"[p{page} #{post_no}]" if page else f"[#{post_no}]"
        if created_at:
            meta = f"{meta} {created_at}"
        lines.append(f"{prefix}{meta} {title}")

    lines.extend([
        "",
        "### 원본 제목 + 본문 + 댓글 세트",
    ])

    for idx, post in enumerate(visible, 1):
        page = post.get("page")
        post_no = post.get("post_no") or post.get("no") or "?"
        title = _source_post_title(post) or "(제목 없음)"
        meta = f"p{page} · #{post_no}" if page else f"#{post_no}"
        created_at = str(post.get("created_at") or "").strip()
        content = _escape_fence(_source_post_content(post, limit=content_limit))
        comments = [_escape_fence(item) for item in _source_post_comments(post)]
        lines.extend([
            "",
            f"#### {idx}. {title}",
            f"- 원본 위치: {meta}",
            f"- 작성 시간: {created_at or '미수집'}",
            "",
            "```text",
            content,
            "```",
        ])
        if comments:
            lines.extend(["", "댓글:"])
            for cidx, comment in enumerate(comments, 1):
                lines.extend([
                    f"- 댓글 {cidx}",
                    "  ```text",
                    f"  {comment}",
                    "  ```",
                ])
        else:
            lines.extend(["", "댓글: (댓글 미수집 또는 없음)"])

    return "\n".join(lines).strip()


def format_actor_briefing_markdown(actor_briefing: dict | None) -> str:
    """Format the public-identity actor briefing for review packages."""

    briefing = actor_briefing or {}
    actors = [item for item in list(briefing.get("actors") or []) if isinstance(item, dict)]
    summary = briefing.get("summary") or {}
    if not actors and not summary:
        return ""

    lines: list[str] = [
        "## 주요 액터 브리핑",
        "",
        "- 기준: 공개 닉네임/ID/IP 힌트로만 묶은 발화 클러스터",
        "- 주의: 실제 개인 식별이 아니라 게시판 안에서 관측된 글쓰기 패턴 요약",
        (
            "- 요약: "
            f"액터 {summary.get('actor_count', 0)}개 · "
            f"주요 {summary.get('major_actor_count', 0)}개 · "
            f"상주 추정 {summary.get('resident_like_count', 0)}개 · "
            f"작성자 정보 없는 댓글 {summary.get('skipped_comment_count', 0)}개 제외"
        ),
    ]

    for idx, actor in enumerate(actors[:10], 1):
        scores = actor.get("scores") or {}
        style = actor.get("style") or {}
        terms = ", ".join(str(term) for term in list(actor.get("top_terms") or [])[:8])
        hours = ", ".join(str(hour) for hour in list(actor.get("active_hours") or [])[:6])
        lines.extend(
            [
                "",
                f"### 액터 {idx}: {actor.get('display_label', actor.get('actor_key', '-'))}",
                (
                    f"- 관측: 글 {actor.get('post_count', 0)}개 · "
                    f"댓글 {actor.get('comment_count', 0)}개 · "
                    f"총 {actor.get('total_count', 0)}회"
                ),
                (
                    "- 점수: "
                    f"상주성 {scores.get('resident_score', 0)} · "
                    f"활동성 {scores.get('activity_score', 0)}"
                ),
                (
                    "- 어투: "
                    f"평균 {style.get('avg_chars', 0)}자 · "
                    f"웃음률 {style.get('laugh_rate', 0)} · "
                    f"질문률 {style.get('question_rate', 0)}"
                ),
                f"- 반복 토큰: {terms or '-'}",
                f"- 관측 시간대: {hours or '-'}",
            ]
        )
        observations = [obs for obs in list(actor.get("observations") or []) if isinstance(obs, dict)]
        if observations:
            lines.extend(["", "관측 예시:"])
            for obs in observations[:3]:
                post_no = obs.get("post_no") or "?"
                kind = obs.get("kind") or "post"
                title = str(obs.get("title") or "").strip()
                excerpt = str(obs.get("excerpt") or "").strip()
                label = f"#{post_no} · {kind}"
                if title:
                    label += f" · {title}"
                lines.append(f"- {label}: {excerpt}")

    return "\n".join(lines).strip()


def format_review_package_markdown(
    *,
    intel_result: dict | None = None,
    gallery_id: str = "",
    sentiment: str = "",
    generation_guidance: str | None = None,
    intel_logs: list | None = None,
    draft_logs: list | None = None,
    scripts: list[dict] | None = None,
    ai_post_comments: list[dict] | None = None,
    log_limit: int = 300,
) -> str:
    """Bundle briefing, logs, and drafts into one Markdown payload for review."""

    lines: list[str] = [
        "# Ghost Protocol 검토 패키지",
        "",
        f"- 복사 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if gallery_id:
        lines.append(f"- 게시판: `{gallery_id}`")
    rhythm = (intel_result or {}).get("posting_rhythm") if intel_result else None
    if isinstance(rhythm, dict) and rhythm.get("interval_count"):
        lines.extend([
            "",
            "## 게시판 글 간격",
            "",
            f"- 표본: 작성시간 {rhythm.get('parsed_count')}개 · 간격 {rhythm.get('interval_count')}개",
            f"- 평균: {board_rhythm.format_seconds(rhythm.get('average_seconds'))}",
            f"- 중앙값: {board_rhythm.format_seconds(rhythm.get('median_seconds'))}",
            f"- 추천 발행 간격: {rhythm.get('recommended_minutes')}분",
            f"- 신뢰도: {rhythm.get('confidence', '-')}",
        ])

    intel_logs = list(intel_logs or [])
    draft_logs = list(draft_logs or [])
    scripts = list(scripts or [])
    ai_post_comments = list(ai_post_comments or [])

    if intel_logs:
        lines.extend([
            "",
            "## 게시판 읽기 로그",
            "",
            f"- 로그 줄 수: {len(intel_logs[-log_limit:])}개",
            "",
            "```text",
        ])
        lines.extend(str(line) for line in intel_logs[-log_limit:])
        lines.append("```")

    if intel_result and intel_result.get("raw_posts"):
        source_posts = format_source_posts_markdown(intel_result.get("raw_posts", []))
        if source_posts:
            lines.extend(["", source_posts])

    if intel_result and intel_result.get("actor_briefing"):
        actor_section = format_actor_briefing_markdown(intel_result.get("actor_briefing"))
        if actor_section:
            lines.extend(["", actor_section])

    if intel_result:
        lines.extend([
            "",
            format_intel_markdown(
                intel_result,
                gallery_id=gallery_id,
                sentiment=sentiment,
                generation_guidance=generation_guidance,
            ),
        ])

    if draft_logs:
        lines.extend([
            "",
            "## 초안 작성 로그",
            "",
            f"- 로그 줄 수: {len(draft_logs[-log_limit:])}개",
            "",
            "```text",
        ])
        lines.extend(str(line) for line in draft_logs[-log_limit:])
        lines.append("```")

    if ai_post_comments:
        lines.extend([
            "",
            "## 발행 글 댓글 모니터링",
            "",
            f"- 기준: 게시글 ID 원장",
            f"- 수집 댓글: {len(ai_post_comments)}개",
        ])
        for row in ai_post_comments[:120]:
            post_no = row.get("post_id", "?")
            author = str(row.get("author") or "").strip()
            feedback = " · 자동 작성 의심" if row.get("marker_feedback") else ""
            meta = f"#{post_no}" + (f" · {author}" if author else "") + feedback
            content = str(row.get("content") or "").strip()
            lines.extend([
                "",
                f"### {meta}",
                "```text",
                content,
                "```",
            ])

    if scripts:
        lines.extend(["", format_scripts_markdown(scripts)])

    if len(lines) <= 3:
        lines.extend(["", "_아직 복사할 검토 데이터가 없습니다._"])

    return "\n".join(lines).strip()


def render_ai_occupation_card(gallery_id: str, view: AiOccupationView) -> str:
    """Render the bot/human occupation card for the Intel panel."""
    safe_gallery = html.escape(gallery_id)
    safe_pct_label = html.escape(view.pct_label)
    safe_ratio_label = html.escape(view.ratio_label)
    return (
        f'<div style="background:#0D1117;border:1px solid rgba(255,75,75,0.30);'
        f'border-radius:18px;padding:20px 28px;margin-bottom:16px;">'
        f'  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">'
        f'    <span style="color:#FF4B4B;font-size:0.60rem;font-weight:700;'
        f'      letter-spacing:3px;text-transform:uppercase">게시판 구성</span>'
        f'    <span style="color:#333;font-size:0.60rem;font-family:inherit">'
        f'      {safe_gallery}'
        f'    </span>'
        f'  </div>'
        f'  <div style="display:flex;align-items:baseline;gap:14px;margin-bottom:14px">'
        f'    <span style="font-size:2.8rem;font-weight:900;color:{view.pct_color};'
        f'      font-family:inherit;line-height:1;letter-spacing:-1px">'
        f'      {safe_pct_label}'
        f'    </span>'
        f'    <span style="color:#555;font-size:0.82rem">{safe_ratio_label}</span>'
        f'  </div>'
        f'  <div style="background:rgba(255,255,255,0.06);border-radius:99px;'
        f'    height:10px;overflow:hidden;margin-bottom:10px">'
        f'    <div style="width:{view.bar_width};height:100%;background:{view.bar_color};'
        f'      border-radius:99px"></div>'
        f'  </div>'
        f'  <div style="display:flex;justify-content:space-between">'
        f'    <span style="color:#00C2A0;font-size:0.72rem">'
        f'      일반 글 &nbsp;{view.human_count}개 &nbsp;({view.human_pct:.1f}%)'
        f'    </span>'
        f'    <span style="color:{view.pct_color};font-size:0.72rem">'
        f'      자동 글 추정 &nbsp;{view.ai_count}개 &nbsp;({view.ai_pct:.1f}%)'
        f'    </span>'
        f'  </div>'
        f'</div>'
    )


def render_intel_briefing_card(
    *,
    gallery_id: str,
    sentiment: str,
    sentiment_class: str,
    hot_topics: list | tuple,
    memes: list | tuple,
    top_keywords: list | tuple,
    stats: dict,
) -> str:
    """Render the main Intel briefing card."""
    hot_chips = "".join(
        f'<span class="intel-chip-hot">{html.escape(str(topic))}</span>'
        for topic in hot_topics
    )
    meme_chips = "".join(
        f'<span class="intel-chip-meme">{html.escape(str(meme))}</span>'
        for meme in memes
    )
    keyword_chips = "".join(
        f'<span class="intel-chip-kw">{html.escape(str(word))}</span>'
        for word in top_keywords[:15]
    )
    stat_pills = (
        f'<span class="intel-stat-pill">제목 <span>{stats.get("titles_count", 0)}</span>개</span>'
        f'<span class="intel-stat-pill">댓글 <span>{stats.get("comments_count", 0)}</span>개</span>'
        f'<span class="intel-stat-pill">키워드 <span>{stats.get("keywords_found", 0)}</span>개</span>'
    )
    meme_body = (
        meme_chips
        if meme_chips
        else '<span style="color:#333;font-size:0.72rem">감지된 밈 없음</span>'
    )

    return (
        f'<div class="intel-card">'
        f'  <div class="intel-header">'
        f'    <span class="intel-title">분위기 리포트</span>'
        f'    <span class="intel-gallery-badge">{html.escape(gallery_id)}</span>'
        f'  </div>'
        f'  <div class="intel-section-label">전체 분위기</div>'
        f'  <div class="intel-sentiment {html.escape(sentiment_class)}">{html.escape(sentiment)}</div>'
        f'  <div class="intel-section-label">뜨거운 이야기</div>'
        f'  <div class="intel-chips">{hot_chips}</div>'
        f'  <div class="intel-section-label">자주 보이는 표현</div>'
        f'  <div class="intel-chips">{meme_body}</div>'
        f'  <div class="intel-section-label" style="margin-top:14px">주요 키워드</div>'
        f'  <div class="intel-chips">{keyword_chips}</div>'
        f'  <div class="intel-stats">{stat_pills}</div>'
        f'</div>'
    )


def compact_text(value: str, limit: int = 220) -> str:
    """Collapse whitespace and trim text for one-screen Intel summaries."""
    text = normalize_ai_briefing_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def normalize_ai_briefing_text(value: object) -> str:
    """Remove small safety-placeholder glitches from model-written briefings."""

    text = " ".join(str(value or "").strip().split())
    text = text.replace("특정 특정 유저", "특정 유저")
    text = text.replace("특정 특정 인물", "특정 인물")
    text = text.replace("특정 특정 집단", "특정 집단")
    text = re.sub(r"(특정 유저)(?:라는\s*)?\1", r"\1", text)
    text = re.sub(r"(특정 인물)(?:이라는\s*)?\1", r"\1", text)
    return text


def render_compact_intel(
    ir: dict,
    *,
    gallery_id: str,
    sentiment: str,
) -> str:
    """Render the compact Intel summary shown above detailed reports."""
    summary = compact_text(
        ir.get("ai_analysis") or ir.get("summary") or "분석 결과가 준비됐습니다."
    )
    guidance = compact_text(ir.get("generation_guidance") or "", 220)
    direction = compact_text(ir.get("summary") or "", 180)
    keywords = ir.get("top_keywords", [])[:8]
    topics = ir.get("hot_topics", [])[:3]
    keyword_html = "".join(
        f'<span>{html.escape(str(keyword))}</span>'
        for keyword in keywords
    ) or '<span>키워드 없음</span>'
    topic_html = "".join(
        f'<b>{html.escape(str(topic))}</b>'
        for topic in topics
    ) or '<b>주요 화제 없음</b>'
    guidance_html = (
        f'  <small class="intel-compact-guidance">{html.escape(guidance)}</small>'
        if guidance else ""
    )

    return (
        '<div class="intel-compact">'
        '  <div class="intel-compact-top">'
        f'    <span>분위기 요약</span><small>{html.escape(gallery_id)} · {html.escape(sentiment)}</small>'
        '  </div>'
        f'  <p>{html.escape(summary)}</p>'
        f'{guidance_html}'
        f'  <div class="intel-compact-topics">{topic_html}</div>'
        f'  <div class="intel-compact-keywords">{keyword_html}</div>'
        f'  <small class="intel-compact-direction">{html.escape(direction)}</small>'
        '</div>'
    )


def build_briefing_topic(
    ir: dict,
    *,
    slot_warning: str | None = None,
) -> str:
    """Build the topic text injected by the compact briefing action."""
    ai_briefing = normalize_ai_briefing_text(ir.get("ai_analysis") or "")
    summary = normalize_ai_briefing_text(ir.get("summary") or "")
    parts = []
    if ai_briefing:
        parts.append(ai_briefing)
    if summary:
        parts.append("씨앗 떡밥: " + summary)
    return "\n".join(parts)


def build_generation_guidance(ir: dict, *, slot_warning: str | None = None) -> str:
    """Build the separate writing-guidance text injected next to the briefing."""
    if intel_result.is_parse_failed(ir):
        return ""
    guidance = (ir.get("generation_guidance") or "").strip()
    parts = [guidance] if guidance else []
    style_block = gallery_style.prompt_block(ir.get("style_profile"))
    if style_block:
        parts.append(style_block)
    composition_block = writing_enrichment.prompt_block(ir.get("composition_profile"))
    if composition_block:
        parts.append(composition_block)
    if slot_warning:
        parts.append(
            "[슬롯 다양성 보정]\n"
            "씨앗 떡밥 A/B/C가 비슷한 명사를 공유합니다. 브리핑의 큰 주제는 유지하되, "
            "초안에서는 같은 말을 반복하지 말고 작품명·구체 표현·독자 반응·반박·해결책·비교처럼 "
            "서로 다른 관점으로 나누어 작성하세요."
        )
    return "\n\n".join(parts)


def format_intel_markdown(
    ir: dict,
    *,
    gallery_id: str,
    sentiment: str,
    generation_guidance: str | None = None,
) -> str:
    """Build a Markdown copy block for the current Intel briefing."""

    stats = ir.get("stats", {}) or {}
    hot_topics = [str(item).strip() for item in ir.get("hot_topics", []) if str(item).strip()]
    memes = [str(item).strip() for item in ir.get("memes", []) if str(item).strip()]
    keywords = [str(item).strip() for item in ir.get("top_keywords", []) if str(item).strip()]
    ai_analysis = normalize_ai_briefing_text(ir.get("ai_analysis") or "")
    generation_guidance = (
        generation_guidance
        if generation_guidance is not None
        else normalize_ai_briefing_text(ir.get("generation_guidance") or "")
    )
    summary = normalize_ai_briefing_text(ir.get("summary") or "")

    lines: list[str] = [
        "# 분위기 브리핑",
        "",
        f"- 게시판: `{gallery_id or '게시판'}`",
        f"- 감성: {sentiment or '알 수 없음'}",
        (
            "- 수집: "
            f"제목 {stats.get('titles_count', 0)}개 · "
            f"댓글 {stats.get('comments_count', 0)}개 · "
            f"키워드 {stats.get('keywords_found', 0)}개"
        ),
    ]
    if ai_analysis:
        lines.extend(["", "## AI 브리핑", ai_analysis])
    if generation_guidance:
        lines.extend(["", "## 작문 지시", generation_guidance])
    if hot_topics:
        lines.extend(["", "## 주요 소재"])
        lines.extend(f"- {item}" for item in hot_topics)
    if memes:
        lines.extend(["", "## 반복 표현"])
        lines.extend(f"- {item}" for item in memes)
    if keywords:
        lines.extend(["", "## 키워드", ", ".join(keywords[:20])])
    if summary:
        lines.extend(["", "## 씨앗 떡밥", summary])
    return "\n".join(lines).strip()


def has_briefing_topic_source(ir: dict) -> bool:
    """Return True when the Intel result has text usable as a topic seed."""
    return intel_result.can_seed_generation(ir)


def render_situation_summary(summary_text: str, ai_analysis_text: str) -> str:
    """Render the optional Intel situation summary card."""
    summary = (summary_text or "").strip()
    analysis = (ai_analysis_text or "").strip()
    if not summary and not analysis:
        return ""

    summary_html = html.escape(summary).replace("\n", "<br>")
    analysis_html = html.escape(analysis).replace("\n", "<br>")
    inner_html = ""
    if analysis_html:
        inner_html += (
            '<div style="color:#6A8FA0;font-size:0.62rem;font-weight:700;'
            'letter-spacing:2px;text-transform:uppercase;margin-bottom:8px">'
            '상황 요약</div>'
            '<p style="margin:0;color:#B8C8D0;font-size:0.9rem;line-height:1.85;">'
            f'{analysis_html}</p>'
        )
    if analysis_html and summary_html:
        inner_html += (
            '<div style="border-top:1px solid rgba(0,240,255,0.15);'
            'margin:16px 0;"></div>'
        )
    if summary_html:
        inner_html += (
            '<div style="color:#555;font-size:0.62rem;font-weight:700;'
            'letter-spacing:2px;text-transform:uppercase;margin-bottom:8px">'
            '원고 방향</div>'
            '<p style="margin:0;color:#D0D0D0;font-size:0.9rem;'
            'line-height:1.85;font-style:italic;">'
            f'{summary_html}</p>'
        )

    return (
        f'<div style="background:rgba(0,240,255,0.04);border:1px solid rgba(0,240,255,0.13);'
        f'border-left:3px solid rgba(0,240,255,0.45);border-radius:0 12px 12px 0;'
        f'padding:16px 22px;margin-top:14px;">'
        f'<div style="color:#555;font-size:0.62rem;font-weight:700;letter-spacing:2px;'
        f'text-transform:uppercase;margin-bottom:12px">읽은 내용</div>'
        f'{inner_html}</div>'
    )


def format_export_limit_caption(
    *,
    post_count: int,
    comment_count: int,
    hard_limit: int,
) -> str:
    """Build the DB export helper caption shown above CSV download buttons."""
    return (
        f"최대 {hard_limit:,}행 · UTF-8 BOM (Excel 한글 호환) · 캐시 5분\n\n"
        + (
            f"⚠️ DB 게시글 {post_count:,}행 중 {hard_limit:,}행만 추출됩니다."
            if post_count > hard_limit
            else ""
        )
        + (
            f"\n⚠️ DB 댓글 {comment_count:,}행 중 {hard_limit:,}행만 추출됩니다."
            if comment_count > hard_limit
            else ""
        )
    )


def render_intel_log_panel(logs: list, *, height_px: int = 160, limit: int = 18) -> str:
    """Render the compact Intel collection log panel."""
    body = "".join(f'<div>{html.escape(str(line))}</div>' for line in logs[-limit:])
    return (
        f'<div class="intel-terminal" style="height:{height_px}px;overflow-y:auto">'
        f'{body}</div>'
    )


def render_intel_running_empty() -> str:
    """Render the Intel empty state while collection is starting."""
    return (
        '<div class="intel-card"><div class="intel-empty">분위기 읽는 중...<br><br>'
        '<span style="color:#D9B06A">게시판의 최근 흐름을 정리하고 있습니다.</span>'
        '</div></div>'
    )


def render_intel_idle_empty() -> str:
    """Render the Intel idle empty state."""
    return (
        '<div class="intel-card"><div class="intel-empty">아직 읽은 분위기가 없습니다.<br><br>'
        '상단에서 게시판을 입력하고<br>'
        '<b style="color:#D9B06A">분위기 읽기</b>를 누르세요.<br><br>'
        '<span style="color:#697380;font-size:0.72rem">최근 결과는 잠시 보관됩니다.</span>'
        '</div></div>'
    )


def build_intel_fig(intel_result: dict) -> "go.Figure | None":
    """Build the keyword frequency chart from an intel result payload."""
    keywords = intel_result.get("top_keywords", [])[:30]
    keyword_counts = intel_result.get("keyword_counts", {})
    if not keywords:
        return None
    if not keyword_counts:
        keyword_counts = {word: len(keywords) - idx for idx, word in enumerate(keywords)}

    n = min(20, len(keywords))
    words = keywords[:n]
    values = [keyword_counts.get(word, 1) for word in words]
    words_r = words[::-1]
    values_r = values[::-1]

    fig = go.Figure(
        go.Bar(
            x=values_r,
            y=words_r,
            orientation="h",
            marker=dict(
                color=values_r,
                colorscale=[
                    [0, "#314355"],
                    [0.45, "#3C8D7D"],
                    [1.0, "#F2B84B"],
                ],
                showscale=False,
                line=dict(width=0),
            ),
            hovertemplate="<b>%{y}</b><br>count: %{x}<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#11151C",
        plot_bgcolor="#11151C",
        height=max(320, n * 22),
        margin=dict(l=0, r=16, t=34, b=8),
        title=dict(
            text="주요 키워드 / TOP 20",
            font=dict(size=11, color="#B7C2CC", family="SUIT Variable, Pretendard, Malgun Gothic, sans-serif"),
            x=0,
        ),
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.06)",
            tickfont=dict(size=9, color="#9AA6B2", family="SUIT Variable, Pretendard, Malgun Gothic, sans-serif"),
            title=None,
            zeroline=False,
        ),
        yaxis=dict(tickfont=dict(size=11, color="#D9E2EC"), title=None, automargin=True),
        hoverlabel=dict(
            bgcolor="#161D27",
            font_size=12,
            font_family="SUIT Variable, Pretendard, Malgun Gothic, sans-serif",
            bordercolor="rgba(242,184,75,0.35)",
        ),
    )
    return fig


def build_test_summary(
    scripts: list,
    intel: dict | None,
    wave_num: int,
    mem: dict | None = None,
) -> str:
    """Build the compact test-mode wave summary shown in the review panel."""
    valid = [script for script in scripts if not script.get("_failed")]
    failed = len(scripts) - len(valid)
    width = 58
    ts = time.strftime("%H:%M:%S")

    lines: list[str] = []
    lines.append("=" * width)
    lines.append(f" 리허설 {wave_num}회차  ·  {ts} ".center(width))
    lines.append("=" * width)
    lines.append("")

    fail_tag = f"  (실패 {failed}개)" if failed else ""
    lines.append(f"[원고] 생성 {len(valid)}개{fail_tag}")
    for idx, script in enumerate(valid, 1):
        persona = (
            script.get("tone")
            or script.get("persona_key")
            or script.get("persona")
            or ""
        )[:14].ljust(14)
        title = (script.get("title") or "")[:36]
        bot_id_tag = f" *{script['bot_identity'][:6]}" if script.get("bot_identity") else ""
        lines.append(f"  {idx:2}. [{persona}]{bot_id_tag}  {title}")
    lines.append("")

    lines.append("[여론]")
    if intel:
        sentiment = intel.get("sentiment", intel.get("overall_sentiment", "-"))
        hot_topics = intel.get("hot_topics", [])
        memes = intel.get("memes", [])
        keywords = intel.get("top_keywords", [])
        stats = intel.get("stats", {})
        lines.append(f"  감성    : {sentiment}")
        if hot_topics:
            lines.append(f"  핫토픽  : {' · '.join(str(item) for item in hot_topics[:5])}")
        if memes:
            lines.append(f"  밈      : {' · '.join(str(item) for item in memes[:4])}")
        if keywords:
            lines.append(f"  키워드  : {', '.join(str(item) for item in keywords[:12])}")
        if stats:
            lines.append(
                "  스캔    : "
                f"제목 {stats.get('titles_count', 0)}개 · "
                f"댓글 {stats.get('comments_count', 0)}개"
            )
    else:
        lines.append("  (여론 데이터 없음)")
    lines.append("")

    if mem is not None:
        lines.append("[사이클 메모리]")
        drift_score = cycle_memory.get_sentiment_score(mem)
        drift_active = cycle_memory.is_drift_active(mem)
        hist = mem.get("sentiment_hist", [])
        banned_topics = cycle_memory.get_banned_topics(mem)
        banned_starts = cycle_memory.get_banned_starts(mem)
        banned_titles = cycle_memory.get_banned_title_keywords(mem)
        cycle_num = mem.get("cycle_count", 0)
        drift_marker = " DRIFT" if drift_active else ""
        lines.append(f"  사이클  : {cycle_num}")
        lines.append(f"  감성합  : {drift_score}{drift_marker}  (hist={hist})")
        if banned_topics:
            lines.append(f"  금지화제: {' / '.join(banned_topics)}")
        if banned_starts:
            lines.append(f"  금지어휘: {' / '.join(banned_starts)}")
        if banned_titles:
            lines.append(f"  금지제목: {' / '.join(banned_titles)}")
        lines.append("")

    return "\n".join(lines)
