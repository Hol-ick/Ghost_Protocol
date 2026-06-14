"""Operational telemetry helpers for the Streamlit workbench.

The functions in this module deliberately avoid Streamlit imports so they can
be tested as ordinary Python.  The UI layer records events here, then renders a
compact cockpit view for long-running read/generate/rehearsal/publish sessions.
"""

from __future__ import annotations

import datetime as _dt
import re
import time
from collections import Counter
from collections.abc import MutableMapping, Sequence
from typing import Any

from ghost_protocol.domain import gallery_purpose


MAX_TIMELINE_EVENTS = 250
MAX_CYCLE_RECORDS = 120


def now_ts() -> float:
    return time.time()


def time_label(ts: float | None = None) -> str:
    return _dt.datetime.fromtimestamp(ts or now_ts()).strftime("%H:%M:%S")


def new_run_id(mode: str) -> str:
    stamp = _dt.datetime.fromtimestamp(now_ts()).strftime("%Y%m%d-%H%M%S")
    safe_mode = re.sub(r"[^a-zA-Z0-9_-]+", "-", mode or "run").strip("-") or "run"
    return f"{safe_mode}-{stamp}"


def compact_text(value: Any, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def ensure_state(state: MutableMapping[str, Any]) -> None:
    state.setdefault("run_id", "")
    state.setdefault("run_started_at", None)
    state.setdefault("run_mode", "idle")
    state.setdefault("run_gallery_id", "")
    state.setdefault("run_target_count", 0)
    state.setdefault("run_timeline", [])
    state.setdefault("run_cycles", [])
    state.setdefault("run_prompt_versions", [])


def start_run(
    state: MutableMapping[str, Any],
    *,
    mode: str,
    gallery_id: str = "",
    target_count: int = 0,
    reset: bool = False,
    detail: str = "",
) -> str:
    """Create or replace the active run metadata and add a start event."""

    ensure_state(state)
    if reset or not state.get("run_id"):
        state["run_id"] = new_run_id(mode)
        state["run_started_at"] = now_ts()
        state["run_timeline"] = []
        state["run_cycles"] = []
    state["run_mode"] = mode
    state["run_gallery_id"] = gallery_id
    state["run_target_count"] = int(target_count or 0)
    append_event(
        state,
        kind="run_start",
        title=f"{mode} start",
        detail=detail or f"gallery={gallery_id or '-'} target={target_count or 0}",
        status="running",
    )
    return str(state["run_id"])


def append_event(
    state: MutableMapping[str, Any],
    *,
    kind: str,
    title: str,
    detail: str = "",
    status: str = "info",
    cycle: int | None = None,
    metrics: dict[str, Any] | None = None,
) -> None:
    ensure_state(state)
    events = state.setdefault("run_timeline", [])
    if not isinstance(events, list):
        events = []
        state["run_timeline"] = events
    events.append(
        {
            "ts": now_ts(),
            "time": time_label(),
            "kind": kind,
            "title": compact_text(title, 120),
            "detail": compact_text(detail, 260),
            "status": status,
            "cycle": cycle,
            "metrics": dict(metrics or {}),
        }
    )
    if len(events) > MAX_TIMELINE_EVENTS:
        del events[:-MAX_TIMELINE_EVENTS]


def _is_failed_script(script: dict[str, Any]) -> bool:
    return bool(script.get("_failed")) or not (
        str(script.get("title") or "").strip()
        and str(script.get("content") or "").strip()
    )


def _failure_reason(script: dict[str, Any]) -> str:
    for key in ("_failure_reason", "_failed_reason", "failure_reason", "reason"):
        value = compact_text(script.get(key), 120)
        if value:
            return value
    stage = compact_text(script.get("_failure_stage") or script.get("stage"), 80)
    if stage:
        return stage
    return "unknown"


def _failure_stage(script: dict[str, Any]) -> str:
    return compact_text(script.get("_failure_stage") or script.get("stage"), 80) or "unknown"


def _tokenize_title(title: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", title or "")
        if token.lower() not in {"this", "that", "with", "from"}
    ]


def summarize_drafts(
    scripts: Sequence[dict[str, Any]] | None,
    *,
    gallery_id: str = "",
    target_count: int = 0,
) -> dict[str, Any]:
    """Return quality counters for generated and failed draft candidates."""

    items = [item for item in (scripts or []) if isinstance(item, dict)]
    valid = [item for item in items if not _is_failed_script(item)]
    failed = [item for item in items if _is_failed_script(item)]
    total = len(items)
    requested = max(int(target_count or 0), total)
    success_rate = (len(valid) / requested) if requested else 0.0

    failure_reasons = Counter(_failure_reason(item) for item in failed)
    failure_stages = Counter(_failure_stage(item) for item in failed)

    normalized_titles = [
        re.sub(r"\s+", " ", str(item.get("title") or "").strip()).lower()
        for item in valid
    ]
    duplicate_titles = {
        title: count
        for title, count in Counter(normalized_titles).items()
        if title and count > 1
    }

    title_terms = Counter()
    for title in normalized_titles:
        title_terms.update(_tokenize_title(title))

    question_titles = sum(1 for title in normalized_titles if title.rstrip().endswith("?"))
    comment_count = 0
    for item in valid:
        comments = item.get("comments")
        if isinstance(comments, list):
            comment_count += len(comments)
        elif item.get("comment") or item.get("target_comment"):
            comment_count += 1

    purpose_count = 0
    if gallery_id:
        for item in valid:
            try:
                if gallery_purpose.text_matches(
                    gallery_id,
                    str(item.get("title") or ""),
                    str(item.get("content") or ""),
                ):
                    purpose_count += 1
            except Exception:
                purpose_count = 0
                break

    if requested == 0:
        status = "idle"
    elif success_rate >= 0.8 and not duplicate_titles:
        status = "good"
    elif success_rate >= 0.5:
        status = "warn"
    else:
        status = "bad"

    return {
        "total": total,
        "requested": requested,
        "valid": len(valid),
        "failed": len(failed),
        "success_rate": success_rate,
        "status": status,
        "failure_reasons": failure_reasons.most_common(5),
        "failure_stages": failure_stages.most_common(5),
        "duplicate_titles": duplicate_titles,
        "top_title_terms": title_terms.most_common(8),
        "question_titles": question_titles,
        "question_ratio": (question_titles / len(valid)) if valid else 0.0,
        "comment_count": comment_count,
        "purpose_count": purpose_count,
        "purpose_ratio": (purpose_count / len(valid)) if valid else 0.0,
    }


def record_cycle(
    state: MutableMapping[str, Any],
    *,
    cycle: int,
    mode: str,
    scripts: Sequence[dict[str, Any]] | None,
    target_count: int = 0,
    gallery_id: str = "",
    status: str = "done",
) -> dict[str, Any]:
    ensure_state(state)
    summary = summarize_drafts(
        scripts,
        gallery_id=gallery_id,
        target_count=target_count,
    )
    record = {
        "ts": now_ts(),
        "time": time_label(),
        "cycle": int(cycle or 0),
        "mode": mode,
        "status": status,
        "summary": summary,
    }
    cycles = state.setdefault("run_cycles", [])
    if not isinstance(cycles, list):
        cycles = []
        state["run_cycles"] = cycles
    cycles.append(record)
    if len(cycles) > MAX_CYCLE_RECORDS:
        del cycles[:-MAX_CYCLE_RECORDS]
    append_event(
        state,
        kind="cycle_done",
        title=f"cycle {record['cycle']} {status}",
        detail=f"{summary['valid']}/{summary['requested']} ready, {summary['failed']} failed",
        status=("ok" if summary["status"] == "good" else summary["status"]),
        cycle=record["cycle"],
        metrics={
            "valid": summary["valid"],
            "failed": summary["failed"],
            "success_rate": round(summary["success_rate"], 3),
        },
    )
    return record


def classify_gemini_logs(logs: Sequence[Any] | None) -> list[dict[str, str]]:
    """Extract actionable Gemini/API diagnostics from log text."""

    joined = "\n".join(str(line) for line in (logs or []))
    lower = joined.lower()
    diagnostics: list[dict[str, str]] = []

    def add(code: str, severity: str, title: str, action: str) -> None:
        if not any(item["code"] == code for item in diagnostics):
            diagnostics.append(
                {
                    "code": code,
                    "severity": severity,
                    "title": title,
                    "action": action,
                }
            )

    if "prepayment credits are depleted" in lower or "billing" in lower:
        add(
            "billing_depleted",
            "critical",
            "Gemini billing credit depleted",
            "Open AI Studio billing/project credits, then retry analysis only.",
        )
    if "429" in lower or "rate limit" in lower or "toomanyrequests" in lower:
        add(
            "rate_limit",
            "warning",
            "Gemini rate limit or quota response",
            "Keep collected data, wait for the suggested cooldown, then retry analysis.",
        )
    if "503" in lower or "serviceunavailable" in lower or "unavailable" in lower:
        add(
            "service_unavailable",
            "warning",
            "Gemini service unavailable",
            "Retry with backoff; collected board data can be reused.",
        )
    model_not_found = bool(
        re.search(r"\bmodel\b.{0,80}\bnot found\b", lower)
        or re.search(r"\bnot found\b.{0,80}\bmodel\b", lower)
        or "model not found" in lower
        or "notfound" in lower and "model" in lower
        or "404" in lower and ("gemini" in lower or "model" in lower)
    )
    if model_not_found:
        add(
            "model_not_found",
            "warning",
            "Configured Gemini model was not found",
            "Check model name and API project access.",
        )
    if "json" in lower and ("parse" in lower or "parsing" in lower):
        add(
            "parse_error",
            "info",
            "Model response parse error",
            "Prompt/response contract may need tightening.",
        )
    return diagnostics


def source_snapshot_health(
    intel_result: dict[str, Any] | None,
    *,
    requested_pages: int = 0,
) -> dict[str, Any]:
    ir = intel_result or {}
    raw_posts = ir.get("raw_posts") or []
    stats = ir.get("stats") or {}
    stat_comment_count = int(
        stats.get("comments")
        or stats.get("comment_count")
        or stats.get("comments_count")
        or 0
    )
    raw_count = len(raw_posts) if isinstance(raw_posts, list) else 0
    body_count = 0
    comment_sets = 0
    comment_count = 0
    if isinstance(raw_posts, list):
        for post in raw_posts:
            if not isinstance(post, dict):
                continue
            if str(post.get("content") or post.get("body") or "").strip():
                body_count += 1
            comments = post.get("comments") or []
            if comments:
                comment_sets += 1
                if isinstance(comments, list):
                    comment_count += len(comments)
    comment_count = max(comment_count, stat_comment_count)

    page_count = int(ir.get("pages") or requested_pages or 0)
    expected_min = page_count * 20 if page_count else 0
    if not ir:
        status = "empty"
        note = "No board snapshot yet"
    elif raw_count == 0:
        status = "warn"
        note = "Snapshot has no source posts"
    elif expected_min and raw_count < expected_min:
        status = "warn"
        note = f"Only {raw_count}/{expected_min}+ source rows captured"
    elif body_count == 0 and comment_count == 0:
        status = "warn"
        note = "Titles captured, but bodies/comments are sparse"
    elif body_count == 0:
        status = "warn"
        note = "Titles/comments captured, but bodies are sparse"
    else:
        status = "good"
        note = "Source snapshot is usable"

    return {
        "status": status,
        "note": note,
        "raw_count": raw_count,
        "body_count": body_count,
        "comment_sets": comment_sets,
        "comment_count": comment_count,
        "pages": page_count,
        "title_count": int(stats.get("titles") or stats.get("title_count") or 0),
        "keyword_count": int(stats.get("keywords") or stats.get("keyword_count") or 0),
    }


def format_ops_markdown(
    *,
    state: MutableMapping[str, Any],
    scripts: Sequence[dict[str, Any]] | None = None,
    logs: Sequence[Any] | None = None,
    intel_result: dict[str, Any] | None = None,
    stability_markdown: str = "",
) -> str:
    ensure_state(state)
    draft = summarize_drafts(
        scripts,
        gallery_id=str(state.get("run_gallery_id") or ""),
        target_count=int(state.get("run_target_count") or 0),
    )
    source = source_snapshot_health(intel_result)
    diagnostics = classify_gemini_logs(logs)
    lines = [
        "# Ghost Protocol 운영 리포트",
        "",
        f"- Run ID: `{state.get('run_id') or '-'}`",
        f"- Mode: `{state.get('run_mode') or 'idle'}`",
        f"- Gallery: `{state.get('run_gallery_id') or '-'}`",
        f"- Drafts: {draft['valid']}/{draft['requested']} ready, {draft['failed']} failed",
        f"- Source: {source['raw_count']} posts · {source['body_count']} bodies · {source['comment_count']} comments",
        "",
        "## Diagnostics",
    ]
    if diagnostics:
        for item in diagnostics:
            lines.append(f"- [{item['severity']}] {item['title']} — {item['action']}")
    else:
        lines.append("- No critical Gemini/API diagnostic detected.")

    if stability_markdown:
        lines.extend(["", stability_markdown.strip()])

    lines.extend(["", "## Recent Timeline"])
    events = list(state.get("run_timeline") or [])[-30:]
    if not events:
        lines.append("- No timeline events.")
    for event in events:
        cycle = f" C{event.get('cycle')}" if event.get("cycle") else ""
        detail = f" — {event.get('detail')}" if event.get("detail") else ""
        lines.append(f"- {event.get('time', '-')}{cycle} [{event.get('status')}] {event.get('title')}{detail}")

    lines.extend(["", "## Cycle Summaries"])
    cycles = list(state.get("run_cycles") or [])[-20:]
    if not cycles:
        lines.append("- No cycle summary yet.")
    for cycle in cycles:
        summary = cycle.get("summary") or {}
        lines.append(
            "- "
            f"C{cycle.get('cycle')} {cycle.get('mode')} "
            f"{summary.get('valid', 0)}/{summary.get('requested', 0)} ready "
            f"({summary.get('failed', 0)} failed)"
        )
    return "\n".join(lines).strip() + "\n"
