"""Run stability policy for long-running Ghost Protocol sessions.

This module keeps stop/warn decisions outside the Streamlit UI so infinite
runs, rehearsal runs, reports, and tests all use the same operational rules.
The rules are intentionally conservative: they pause the loop on infrastructure
or collection failures, not on ordinary draft variation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ghost_protocol.application import observability


DEFAULT_MAX_INFINITE_CYCLES = 24
DEFAULT_MAX_CONSECUTIVE_BAD_CYCLES = 3
DEFAULT_MAX_PUBLISH_FAILURES = 3
DEFAULT_MAX_FEEDBACK_ALERTS = 3


@dataclass(frozen=True)
class StabilityThresholds:
    max_infinite_cycles: int = DEFAULT_MAX_INFINITE_CYCLES
    max_consecutive_bad_cycles: int = DEFAULT_MAX_CONSECUTIVE_BAD_CYCLES
    max_publish_failures: int = DEFAULT_MAX_PUBLISH_FAILURES
    max_feedback_alerts: int = DEFAULT_MAX_FEEDBACK_ALERTS
    stop_on_billing_issue: bool = True
    stop_on_empty_source: bool = True


def _as_int(value: object, *, default: int, lower: int = 0, upper: int = 999) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(upper, parsed))


def thresholds_from_state(state: Mapping[str, Any] | None) -> StabilityThresholds:
    state = state or {}
    return StabilityThresholds(
        max_infinite_cycles=_as_int(
            state.get("ops_max_infinite_cycles"),
            default=DEFAULT_MAX_INFINITE_CYCLES,
            lower=1,
            upper=500,
        ),
        max_consecutive_bad_cycles=_as_int(
            state.get("ops_max_consecutive_bad_cycles"),
            default=DEFAULT_MAX_CONSECUTIVE_BAD_CYCLES,
            lower=1,
            upper=20,
        ),
        max_publish_failures=_as_int(
            state.get("ops_max_publish_failures"),
            default=DEFAULT_MAX_PUBLISH_FAILURES,
            lower=0,
            upper=100,
        ),
        max_feedback_alerts=_as_int(
            state.get("ops_max_feedback_alerts"),
            default=DEFAULT_MAX_FEEDBACK_ALERTS,
            lower=0,
            upper=100,
        ),
        stop_on_billing_issue=bool(state.get("ops_stop_on_billing_issue", True)),
        stop_on_empty_source=bool(state.get("ops_stop_on_empty_source", True)),
    )


def infer_run_phase(state: Mapping[str, Any] | None) -> str:
    """Return a compact phase label from the current session flags."""

    state = state or {}
    if state.get("intel_running"):
        return "reading"
    if state.get("batch_generating"):
        if state.get("_infinite_refill_round"):
            return "refilling"
        if state.get("wave_test_mode"):
            return "rehearsing"
        return "generating"
    if state.get("swarm_running"):
        return "publishing"
    if state.get("review_ready"):
        return "reviewing"
    if state.get("intel_result"):
        return "briefing"
    return "idle"


def _is_bad_generation_cycle(cycle: Mapping[str, Any]) -> bool:
    mode = str(cycle.get("mode") or "")
    if mode.endswith("-refill"):
        return False
    summary = cycle.get("summary") or {}
    if not isinstance(summary, Mapping):
        return False
    if summary.get("status") == "bad":
        return True
    requested = int(summary.get("requested") or 0)
    valid = int(summary.get("valid") or 0)
    return requested > 0 and valid == 0


def consecutive_bad_generation_cycles(cycles: Sequence[Any] | None) -> int:
    count = 0
    for cycle in reversed(list(cycles or [])):
        if not isinstance(cycle, Mapping):
            continue
        if _is_bad_generation_cycle(cycle):
            count += 1
            continue
        if str(cycle.get("mode") or "").endswith("-refill"):
            continue
        break
    return count


def ai_feedback_summary(comments: Sequence[Any] | None) -> dict[str, int]:
    total = 0
    flagged = 0
    for item in comments or []:
        if not isinstance(item, Mapping):
            continue
        total += 1
        if int(item.get("marker_feedback") or 0):
            flagged += 1
    return {"total": total, "flagged": flagged}


def evaluate_stability(
    state: Mapping[str, Any] | None,
    *,
    scripts: Sequence[dict[str, Any]] | None = None,
    logs: Sequence[Any] | None = None,
    intel_result: dict[str, Any] | None = None,
    ai_comments: Sequence[Any] | None = None,
    thresholds: StabilityThresholds | None = None,
) -> dict[str, Any]:
    """Evaluate whether the current run is healthy, degraded, or should pause."""

    state = state or {}
    thresholds = thresholds or thresholds_from_state(state)
    mode = str(state.get("run_mode") or "idle")
    phase = infer_run_phase(state)
    diagnostics = observability.classify_gemini_logs(logs)
    source = observability.source_snapshot_health(
        intel_result,
        requested_pages=int(state.get("intel_pages") or 0),
    )
    draft = observability.summarize_drafts(
        scripts,
        gallery_id=str(state.get("run_gallery_id") or state.get("target_gallery_id") or ""),
        target_count=int(state.get("run_target_count") or state.get("swarm_wave_total") or 0),
    )
    cycles = list(state.get("run_cycles") or [])
    cycle_count = len(
        [
            cycle
            for cycle in cycles
            if isinstance(cycle, Mapping)
            and str(cycle.get("mode") or "") in {"infinite", "rehearsal"}
        ]
    )
    bad_cycles = consecutive_bad_generation_cycles(cycles)
    publish_failures = int(state.get("posts_failed") or 0)
    feedback = ai_feedback_summary(ai_comments)

    findings: list[dict[str, Any]] = []

    def add(
        code: str,
        severity: str,
        title: str,
        action: str,
        *,
        stop: bool = False,
    ) -> None:
        findings.append(
            {
                "code": code,
                "severity": severity,
                "title": title,
                "action": action,
                "stop": bool(stop),
            }
        )

    diagnostic_codes = {item["code"] for item in diagnostics}
    if thresholds.stop_on_billing_issue and "billing_depleted" in diagnostic_codes:
        add(
            "billing_stop",
            "critical",
            "Gemini 결제/크레딧 문제",
            "수집 데이터는 유지하고 무한 실행을 멈춘 뒤 결제 상태를 확인하세요.",
            stop=True,
        )
    elif "rate_limit" in diagnostic_codes:
        add(
            "rate_limit_backoff",
            "warning",
            "Gemini 호출 제한",
            "분석/생성 단계만 백오프 후 재시도하세요.",
        )

    if thresholds.stop_on_empty_source and source.get("status") == "warn":
        raw_count = int(source.get("raw_count") or 0)
        if raw_count == 0:
            add(
                "source_empty_stop",
                "critical",
                "원본 수집 없음",
                "게시판 읽기부터 다시 수행해야 합니다.",
                stop=True,
            )
        elif int(source.get("body_count") or 0) == 0 and int(source.get("comment_count") or 0) == 0:
            add(
                "source_sparse",
                "warning",
                "본문/댓글 수집 부족",
                "원고 품질 검토 전 수집 방식을 점검하세요.",
            )

    if bad_cycles >= thresholds.max_consecutive_bad_cycles:
        add(
            "bad_cycle_stop",
            "critical",
            "연속 생성 품질 저하",
            f"{bad_cycles}회 연속 생성 품질이 낮아 무한 실행을 멈춥니다.",
            stop=True,
        )

    if (
        thresholds.max_publish_failures > 0
        and publish_failures >= thresholds.max_publish_failures
    ):
        add(
            "publish_fail_stop",
            "critical",
            "발행 실패 누적",
            f"발행 실패 {publish_failures}회가 누적되어 계정/페이지 상태 확인이 필요합니다.",
            stop=True,
        )

    if mode == "infinite" and cycle_count >= thresholds.max_infinite_cycles:
        add(
            "cycle_cap_stop",
            "warning",
            "무한 실행 상한 도달",
            f"{cycle_count}개 사이클을 완료해 점검을 위해 멈춥니다.",
            stop=True,
        )

    if (
        thresholds.max_feedback_alerts > 0
        and feedback["flagged"] >= thresholds.max_feedback_alerts
    ):
        add(
            "feedback_alert_stop",
            "warning",
            "댓글 피드백 경고 누적",
            f"감시 댓글 중 경고 {feedback['flagged']}개가 감지되었습니다.",
            stop=True,
        )

    severity_rank = {"critical": 3, "warning": 2, "info": 1}
    top_severity = "good"
    if findings:
        top = max(findings, key=lambda item: severity_rank.get(item["severity"], 0))
        top_severity = str(top["severity"])

    return {
        "mode": mode,
        "phase": phase,
        "status": top_severity,
        "stop_recommended": any(item["stop"] for item in findings),
        "findings": findings,
        "source": source,
        "draft": draft,
        "feedback": feedback,
        "bad_cycles": bad_cycles,
        "cycle_count": cycle_count,
        "publish_failures": publish_failures,
    }


def format_stability_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "## Stability",
        f"- Status: `{report.get('status', 'good')}`",
        f"- Phase: `{report.get('phase', 'idle')}`",
        f"- Stop recommended: `{bool(report.get('stop_recommended'))}`",
    ]
    findings = list(report.get("findings") or [])
    if not findings:
        lines.append("- Findings: no blocking stability issue.")
    else:
        lines.append("- Findings:")
        for item in findings:
            stop = " stop" if item.get("stop") else ""
            lines.append(
                f"  - [{item.get('severity')}{stop}] {item.get('title')} — {item.get('action')}"
            )
    feedback = report.get("feedback") or {}
    lines.append(
        f"- Watched comments: {int(feedback.get('total') or 0)} total, "
        f"{int(feedback.get('flagged') or 0)} flagged"
    )
    return "\n".join(lines)
