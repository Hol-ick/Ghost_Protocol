"""Lightweight local-LLM usage accounting and budget guards.

This module is intentionally independent from Streamlit.  The UI writes the
operator's cost controls into environment variables, while ``GhostBrain`` records
actual provider calls here.  Keeping the ledger process-local is enough for the
current threaded workbench and makes tests straightforward.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import Counter
import json
from pathlib import Path
from typing import Any


TRUTHY = {"1", "true", "yes", "y", "on"}
DEFAULT_MAX_CALLS_PER_RUN = 0
DEFAULT_JUDGE_SAMPLE_RATE = 0.35


class LLMBudgetExceededError(RuntimeError):
    """Raised before an LLM call when the configured run budget is exhausted."""


class LLMCostOrQuotaError(RuntimeError):
    """Raised when a provider reports exhausted quota or credits."""


_lock = threading.Lock()
_run_id = ""
_run_mode = ""
_target_count = 0
_started_at = time.time()
_next_call_id = 0
_events: list[dict[str, Any]] = []
_totals: Counter[str] = Counter()
_by_label: Counter[str] = Counter()
_by_model: Counter[str] = Counter()
_error_counts: Counter[str] = Counter()
_estimated_prompt_chars = 0
_estimated_response_chars = 0
_usage_tokens: Counter[str] = Counter()
_HISTORY_PATH = Path(__file__).resolve().parents[2] / "data" / "ollama_usage_history.json"
_MAX_HISTORY = 80


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUTHY


def _env_int(name: str, default: int = 0, *, lower: int = 0, upper: int = 1_000_000) -> int:
    try:
        value = int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        value = default
    return max(lower, min(upper, value))


def _env_float(name: str, default: float, *, lower: float = 0.0, upper: float = 1.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(lower, min(upper, value))


def cost_saver_enabled() -> bool:
    return _env_bool("LLM_COST_SAVER_MODE", default=False)


def max_calls_per_run() -> int:
    return _env_int("LLM_MAX_CALLS_PER_RUN", DEFAULT_MAX_CALLS_PER_RUN, lower=0)


def trend_cache_ttl_seconds() -> int:
    return _env_int("LLM_TREND_CACHE_TTL_SEC", 900, lower=0, upper=86_400)


def judge_mode() -> str:
    mode = (os.getenv("LLM_JUDGE_MODE") or "auto").strip().lower()
    return mode if mode in {"auto", "all", "sample", "off"} else "auto"


def judge_sample_rate() -> float:
    return _env_float("LLM_JUDGE_SAMPLE_RATE", DEFAULT_JUDGE_SAMPLE_RATE, lower=0.0, upper=1.0)


def _run_mode_from_id(run_id: str) -> str:
    text = str(run_id or "").strip()
    if not text:
        return ""
    match = re.match(r"^([A-Za-z0-9_-]+)-\d{8}-\d{6}$", text)
    if match:
        return match.group(1)
    return text.split("-", 1)[0]


def _read_history(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or _HISTORY_PATH
    try:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_history(items: list[dict[str, Any]], path: Path | None = None) -> None:
    path = path or _HISTORY_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(items[-_MAX_HISTORY:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        return


def _snapshot_unlocked() -> dict[str, Any]:
    return {
        "run_id": _run_id,
        "mode": _run_mode,
        "target_count": int(_target_count),
        "started_at": _started_at,
        "elapsed_seconds": max(0.0, time.time() - _started_at),
        "physical_calls": int(_totals["physical_calls"]),
        "successful_calls": int(_totals["successful_calls"]),
        "failed_calls": int(_totals["failed_calls"]),
        "by_label": dict(_by_label),
        "by_model": dict(_by_model),
        "errors": dict(_error_counts),
        "estimated_prompt_chars": int(_estimated_prompt_chars),
        "estimated_response_chars": int(_estimated_response_chars),
        "usage_tokens": dict(_usage_tokens),
        "max_calls_per_run": max_calls_per_run(),
        "cost_saver": cost_saver_enabled(),
        "judge_mode": judge_mode(),
        "trend_cache_ttl_sec": trend_cache_ttl_seconds(),
    }


def _archive_current_run_unlocked() -> None:
    if not _run_id or not _run_mode or int(_totals["physical_calls"]) <= 0:
        return
    entry = _snapshot_unlocked()
    entry["ended_at"] = time.time()
    run_id = str(entry.get("run_id") or "")
    history = [
        item for item in _read_history()
        if str(item.get("run_id") or "") != run_id
    ]
    history.append(entry)
    _write_history(history)


def reset_run(run_id: str = "", *, mode: str = "", target_count: int = 0) -> None:
    """Start a fresh process-local accounting window."""

    global _run_id, _run_mode, _target_count, _started_at, _next_call_id
    global _estimated_prompt_chars, _estimated_response_chars
    with _lock:
        _archive_current_run_unlocked()
        _run_id = run_id
        _run_mode = str(mode or _run_mode_from_id(run_id)).strip()
        try:
            _target_count = max(0, int(target_count or 0))
        except (TypeError, ValueError):
            _target_count = 0
        _started_at = time.time()
        _next_call_id = 0
        _events.clear()
        _totals.clear()
        _by_label.clear()
        _by_model.clear()
        _error_counts.clear()
        _usage_tokens.clear()
        _estimated_prompt_chars = 0
        _estimated_response_chars = 0


def finalize_run() -> dict[str, Any]:
    """Persist the current run snapshot without starting a new accounting window.

    ``reset_run`` archives the previous run before creating the next one, but a
    desktop app can be closed before the next run starts.  Finalizing on worker
    completion keeps the comparison baseline current and is idempotent because
    history is upserted by ``run_id``.
    """

    with _lock:
        _archive_current_run_unlocked()
        return dict(_snapshot_unlocked())


def _compact_label(label: str) -> str:
    return (label or "unknown").split(":", 1)[0]


def estimate_chars(value: Any) -> int:
    """Cheap prompt-size estimate for strings, dicts, lists and SDK-ish values."""

    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, dict):
        return sum(estimate_chars(k) + estimate_chars(v) for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        return sum(estimate_chars(item) for item in value)
    return len(str(value))


def _usage_value(metadata: Any, name: str) -> int:
    if metadata is None:
        return 0
    if isinstance(metadata, dict):
        raw = metadata.get(name)
    else:
        raw = getattr(metadata, name, None)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _extract_response_chars(response: Any) -> int:
    try:
        return len(str(getattr(response, "text", "") or ""))
    except Exception:
        return 0


def _classify_error(err: Exception) -> str:
    text = str(err).lower()
    if is_billing_or_credit_error(err):
        return "billing_depleted"
    if "429" in text or "rate limit" in text or "resource_exhausted" in text:
        return "rate_limit"
    if "503" in text or "unavailable" in text:
        return "service_unavailable"
    return err.__class__.__name__


def is_billing_or_credit_error(err: Exception) -> bool:
    text = str(err).lower()
    return any(
        marker in text
        for marker in (
            "prepayment credits are depleted",
            "credits are depleted",
            "billing",
            "payment",
            "insufficient credits",
        )
    )


def begin_call(*, label: str, model: str, contents: Any = None) -> dict[str, Any]:
    """Register a planned physical local-LLM call and enforce max-call budget."""

    global _next_call_id, _estimated_prompt_chars
    label_key = _compact_label(label)
    prompt_chars = estimate_chars(contents)
    with _lock:
        max_calls = max_calls_per_run()
        current = int(_totals["physical_calls"])
        if max_calls and current >= max_calls:
            raise LLMBudgetExceededError(
                f"LLM call budget exceeded: {current}/{max_calls} calls used"
            )
        _next_call_id += 1
        call = {
            "id": _next_call_id,
            "ts": time.time(),
            "label": label_key,
            "model": model or "",
            "prompt_chars": prompt_chars,
        }
        _events.append({**call, "status": "started"})
        if len(_events) > 500:
            del _events[:-500]
        _totals["physical_calls"] += 1
        _by_label[label_key] += 1
        if model:
            _by_model[model] += 1
        _estimated_prompt_chars += prompt_chars
        return call


def record_success(call: dict[str, Any], response: Any) -> None:
    global _estimated_response_chars
    response_chars = _extract_response_chars(response)
    metadata = getattr(response, "usage", None)
    if metadata is None:
        metadata = getattr(response, "usage_metadata", None)
    with _lock:
        _totals["successful_calls"] += 1
        _estimated_response_chars += response_chars
        for source_name, target_name in (
            ("prompt_token_count", "prompt_tokens"),
            ("candidates_token_count", "candidate_tokens"),
            ("total_token_count", "total_tokens"),
            ("prompt_eval_count", "prompt_tokens"),
            ("eval_count", "candidate_tokens"),
        ):
            value = _usage_value(metadata, source_name)
            if value:
                _usage_tokens[target_name] += value
        _events.append({**call, "status": "ok", "response_chars": response_chars})
        if len(_events) > 500:
            del _events[:-500]


def record_error(call: dict[str, Any] | None, err: Exception) -> None:
    code = _classify_error(err)
    with _lock:
        _totals["failed_calls"] += 1
        _error_counts[code] += 1
        if call:
            _events.append({**call, "status": "error", "error": code})
            if len(_events) > 500:
                del _events[:-500]


def should_try_fallback_after_error(err: Exception) -> bool:
    """Return False for billing/quota states where another model cannot help."""

    if is_billing_or_credit_error(err):
        return False
    if _env_bool("LLM_DISABLE_FALLBACK_ON_QUOTA", default=True):
        text = str(err).lower()
        if "quota" in text and "rate" not in text and "429" not in text:
            return False
    return True


def should_run_llm_judge(*, wave: int, attempt: int, has_banned_topics: bool = False) -> bool:
    """Decide whether the extra LLM judge call is worth spending."""

    mode = judge_mode()
    if mode == "off":
        return False
    if mode == "all":
        return True
    if not cost_saver_enabled() and mode == "auto":
        return True
    if has_banned_topics:
        return True
    if attempt > 0:
        return True
    rate = judge_sample_rate()
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    every = max(1, round(1 / rate))
    return max(1, int(wave or 1)) % every == 0


def snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_snapshot_unlocked())


def usage_comparison(*, history_limit: int = 10) -> dict[str, Any]:
    """Compare current run usage against recent historical runs of the same mode."""

    current = snapshot()
    history = _read_history()
    mode = str(current.get("mode") or "")
    candidates = [
        item for item in history
        if (not mode or str(item.get("mode") or "") == mode)
        and str(item.get("run_id") or "") != str(current.get("run_id") or "")
    ]
    if not candidates:
        candidates = [
            item for item in history
            if str(item.get("run_id") or "") != str(current.get("run_id") or "")
        ]
    candidates = candidates[-max(1, int(history_limit or 1)):]
    if not candidates:
        return {
            "has_baseline": False,
            "current": current,
            "baseline_count": 0,
        }

    def avg(key: str) -> float:
        return sum(float(item.get(key) or 0) for item in candidates) / len(candidates)

    baseline_calls = avg("physical_calls")
    baseline_prompt = avg("estimated_prompt_chars")
    baseline_response = avg("estimated_response_chars")
    current_calls = float(current.get("physical_calls") or 0)
    current_prompt = float(current.get("estimated_prompt_chars") or 0)
    current_response = float(current.get("estimated_response_chars") or 0)

    def pct_delta(current_value: float, baseline_value: float) -> float | None:
        if baseline_value <= 0:
            return None
        return (current_value - baseline_value) / baseline_value * 100.0

    def label_avg(label: str) -> float:
        return sum(
            float((item.get("by_label") or {}).get(label) or 0)
            for item in candidates
        ) / len(candidates)

    judge_current = float((current.get("by_label") or {}).get("judge_post") or 0)
    judge_baseline = label_avg("judge_post")

    return {
        "has_baseline": True,
        "current": current,
        "baseline_count": len(candidates),
        "baseline_mode": mode or "all",
        "baseline_avg_calls": baseline_calls,
        "baseline_avg_prompt_chars": baseline_prompt,
        "baseline_avg_response_chars": baseline_response,
        "baseline_avg_judge_calls": judge_baseline,
        "call_delta": current_calls - baseline_calls,
        "prompt_delta": current_prompt - baseline_prompt,
        "response_delta": current_response - baseline_response,
        "judge_delta": judge_current - judge_baseline,
        "call_delta_pct": pct_delta(current_calls, baseline_calls),
        "prompt_delta_pct": pct_delta(current_prompt, baseline_prompt),
        "response_delta_pct": pct_delta(current_response, baseline_response),
        "judge_delta_pct": pct_delta(judge_current, judge_baseline),
    }


def resource_summary(*, history_limit: int = 10) -> dict[str, Any]:
    """Return UI-ready local-LLM resource counters and comparison hints."""

    current = snapshot()
    comparison = usage_comparison(history_limit=history_limit)
    budget = int(current.get("max_calls_per_run") or 0)
    calls = int(current.get("physical_calls") or 0)
    budget_ratio = (calls / budget) if budget else 0.0
    by_label = current.get("by_label") or {}
    judge_calls = int(by_label.get("judge_post") or 0)
    generate_calls = int(by_label.get("generate_post") or 0)
    analyze_calls = int(by_label.get("analyze_trend") or 0)
    usage_tokens = current.get("usage_tokens") or {}
    prompt_tokens = int(usage_tokens.get("prompt_tokens") or 0)
    candidate_tokens = int(usage_tokens.get("candidate_tokens") or 0)
    total_tokens = int(usage_tokens.get("total_tokens") or 0)
    status = "good"
    if budget and budget_ratio >= 1:
        status = "bad"
    elif budget and budget_ratio >= 0.8:
        status = "warn"
    elif int(current.get("failed_calls") or 0):
        status = "warn"

    return {
        "status": status,
        "run_id": current.get("run_id", ""),
        "mode": current.get("mode", ""),
        "target_count": int(current.get("target_count") or 0),
        "calls": calls,
        "budget": budget,
        "budget_ratio": budget_ratio,
        "successful_calls": int(current.get("successful_calls") or 0),
        "failed_calls": int(current.get("failed_calls") or 0),
        "generate_calls": generate_calls,
        "judge_calls": judge_calls,
        "analyze_calls": analyze_calls,
        "prompt_chars": int(current.get("estimated_prompt_chars") or 0),
        "response_chars": int(current.get("estimated_response_chars") or 0),
        "prompt_tokens": prompt_tokens,
        "candidate_tokens": candidate_tokens,
        "total_tokens": total_tokens,
        "has_usage_tokens": bool(total_tokens or prompt_tokens or candidate_tokens),
        "cost_saver": bool(current.get("cost_saver")),
        "judge_mode": str(current.get("judge_mode") or ""),
        "trend_cache_ttl_sec": int(current.get("trend_cache_ttl_sec") or 0),
        "comparison": comparison,
    }


def format_short_status() -> str:
    data = snapshot()
    budget = data["max_calls_per_run"]
    calls = data["physical_calls"]
    budget_text = f"{calls}/{budget}" if budget else str(calls)
    labels = ", ".join(
        f"{key}:{value}" for key, value in sorted(data["by_label"].items())
    ) or "-"
    return (
        f"LLM calls {budget_text} · labels {labels} · "
        f"prompt≈{data['estimated_prompt_chars']} chars · response≈{data['estimated_response_chars']} chars"
    )
