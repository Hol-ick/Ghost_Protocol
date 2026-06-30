"""Pure helpers for building batch generation run settings.

The Streamlit page owns widgets and reruns, but the rules for draft,
infinite, and rehearsal modes should be deterministic and testable.  Keeping
those rules here reduces accidental UI-state regressions in ``app.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ghost_protocol.application import operator_settings
from ghost_protocol.application import rehearsal as rehearsal_flow


@dataclass(frozen=True)
class BatchRunSetup:
    """Resolved settings for one draft-generation run."""

    run_mode: str
    actual_count: int
    worker_topic: str
    run_detail: str
    cycle_start_detail: str
    prompt_version: dict[str, Any]
    batch_config: dict[str, Any]
    worker_kwargs: dict[str, Any]
    initial_log_lines: list[str]
    rehearsal_cycle_limit: int
    rehearsal_anchor_posts: list[dict[str, Any]]
    rehearsal_anchor_topic: str


def _append_guidance(topic: str, guidance: str) -> str:
    topic_text = str(topic or "").strip()
    guidance_text = str(guidance or "").strip()
    if not guidance_text:
        return topic_text
    return f"{topic_text}\n\n[작문 지시]\n{guidance_text}".strip()


def _coerce_posts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _mode_labels(*, infinite: bool, rehearsal: bool) -> list[str]:
    labels: list[str] = []
    if infinite:
        labels.append("무한 실행")
    if rehearsal:
        labels.append("리허설")
    return labels


def build_batch_run_setup(
    *,
    api_key: str,
    topic: str,
    guidance: str,
    requested_count: int,
    gallery_id: str,
    gallery_type: str,
    tone: str,
    length: str,
    headless: bool,
    infinite: bool,
    rehearsal: bool,
    style_profile: Any = None,
    composition_profile: Any = None,
    wave_interval_min: int | float = 1,
    wave_interval_max: int | float = 3,
    publish_interval_minutes: int | float = 3,
    rehearsal_cycle_limit: int | None = None,
    intel_result: Mapping[str, Any] | None = None,
    ai_comment_watch_limit: int | None = None,
) -> BatchRunSetup:
    """Resolve UI inputs into stable run configuration.

    Infinite and rehearsal modes intentionally generate 10 drafts per cycle,
    regardless of the ordinary draft count widget.  This prevents stale UI
    counts from making loops publish a partial batch.
    """

    is_infinite = bool(infinite)
    is_rehearsal = bool(rehearsal)
    actual_count = 10 if (is_infinite or is_rehearsal) else max(1, int(requested_count or 1))
    resolved_cycle_limit = rehearsal_flow.normalize_cycle_limit(rehearsal_cycle_limit)
    intel = dict(intel_result or {})
    rehearsal_anchor_posts = _coerce_posts(intel.get("raw_posts")) if is_rehearsal else []
    worker_topic = _append_guidance(topic, guidance)
    rehearsal_anchor_topic = str(topic or worker_topic or "").strip()
    run_mode = "rehearsal" if is_rehearsal else ("infinite" if is_infinite else "draft")

    batch_config = {
        "api_key": api_key,
        "topic": worker_topic,
        "briefing": str(topic or "").strip(),
        "guidance": str(guidance or "").strip(),
        "wave_count": actual_count,
        "gallery_id": str(gallery_id or "").strip(),
        "gallery_type": gallery_type,
        "tone": tone,
        "length": length,
        "headless": bool(headless),
        "infinite": is_infinite,
        "style_profile": style_profile,
        "composition_profile": composition_profile,
        "wave_interval_min": wave_interval_min,
        "wave_interval_max": wave_interval_max,
        "publish_interval_minutes": publish_interval_minutes,
        "wave_test_mode": is_rehearsal,
        "rehearsal": is_rehearsal,
        "rehearsal_cycle": 1,
        "rehearsal_cycle_limit": resolved_cycle_limit,
        "rehearsal_anchor_posts": rehearsal_anchor_posts,
        "rehearsal_anchor_topic": rehearsal_anchor_topic,
        "ai_disclosure_enabled": False,
        "ai_disclosure_marker": operator_settings.DEFAULT_PUBLIC_AI_MARKER,
        "ai_comment_watch_limit": operator_settings.normalize_ai_comment_watch_limit(
            ai_comment_watch_limit
        ),
    }

    worker_kwargs = {
        "api_key": api_key,
        "topic": worker_topic,
        "wave_count": actual_count,
        "gallery_id": str(gallery_id or "").strip(),
        "gallery_type": gallery_type,
        "tone": tone,
        "length": length,
        "infinite": is_infinite,
        "style_profile": style_profile,
        "composition_profile": composition_profile,
        "rehearsal": is_rehearsal,
        "rehearsal_cycle": 1,
        "rehearsal_cycle_limit": resolved_cycle_limit,
        "rehearsal_anchor_posts": rehearsal_anchor_posts,
        "rehearsal_anchor_topic": rehearsal_anchor_topic,
    }

    mode_text = " + ".join(_mode_labels(infinite=is_infinite, rehearsal=is_rehearsal)) or "단일 묶음"
    initial_log_lines = [f"[MODE] 실행 모드 — {mode_text}"]
    if is_infinite:
        initial_log_lines.append(
            "[∞] 무한모드 시작 — 생성과 발행이 끝나면 다음 묶음으로 자동 진행합니다."
        )
    if is_rehearsal:
        initial_log_lines.append(
            f"[REHEARSAL] 시작 — {resolved_cycle_limit}사이클 x 10개, "
            f"실제 게시 없이 원고와 원본 앵커 {len(rehearsal_anchor_posts)}개를 재분석합니다."
        )

    return BatchRunSetup(
        run_mode=run_mode,
        actual_count=actual_count,
        worker_topic=worker_topic,
        run_detail=(
            f"topic_chars={len(str(topic or ''))} guidance_chars={len(str(guidance or ''))} "
            f"cycles={resolved_cycle_limit if is_rehearsal else 1}"
        ),
        cycle_start_detail=f"target={actual_count} rehearsal={is_rehearsal}",
        prompt_version={
            "mode": run_mode,
            "style_profile": bool(style_profile),
            "composition_profile": bool(composition_profile),
        },
        batch_config=batch_config,
        worker_kwargs=worker_kwargs,
        initial_log_lines=initial_log_lines,
        rehearsal_cycle_limit=resolved_cycle_limit,
        rehearsal_anchor_posts=rehearsal_anchor_posts,
        rehearsal_anchor_topic=rehearsal_anchor_topic,
    )
