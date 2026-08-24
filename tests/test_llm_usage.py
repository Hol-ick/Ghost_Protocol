import json

import pytest

from ghost_protocol.application import llm_usage


def test_budget_limit_blocks_before_physical_call(monkeypatch):
    monkeypatch.setenv("LLM_MAX_CALLS_PER_RUN", "1")
    llm_usage.reset_run("unit-budget")

    llm_usage.begin_call(label="generate_post", model="m", contents="hello")

    with pytest.raises(llm_usage.LLMBudgetExceededError):
        llm_usage.begin_call(label="generate_post", model="m", contents="again")


def test_judge_sampling_respects_cost_saver(monkeypatch):
    monkeypatch.setenv("LLM_COST_SAVER_MODE", "1")
    monkeypatch.setenv("LLM_JUDGE_MODE", "auto")
    monkeypatch.setenv("LLM_JUDGE_SAMPLE_RATE", "0.5")

    assert not llm_usage.should_run_llm_judge(wave=1, attempt=0)
    assert llm_usage.should_run_llm_judge(wave=2, attempt=0)
    assert llm_usage.should_run_llm_judge(wave=1, attempt=1)
    assert llm_usage.should_run_llm_judge(wave=1, attempt=0, has_banned_topics=True)


def test_billing_error_detection():
    err = Exception("Your prepayment credits are depleted. Please manage billing.")
    assert llm_usage.is_billing_or_credit_error(err)
    assert not llm_usage.should_try_fallback_after_error(err)


def test_usage_comparison_uses_recent_same_mode_baseline(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_usage, "_HISTORY_PATH", tmp_path / "usage.json")
    monkeypatch.setenv("LLM_MAX_CALLS_PER_RUN", "0")

    llm_usage.reset_run("draft-20260630-000001", mode="draft", target_count=10)
    llm_usage.begin_call(label="generate_post", model="m", contents="a" * 10)
    llm_usage.begin_call(label="judge_post", model="m", contents="b" * 5)

    llm_usage.reset_run("draft-20260630-000002", mode="draft", target_count=10)
    llm_usage.begin_call(label="generate_post", model="m", contents="c" * 10)

    comparison = llm_usage.usage_comparison()

    assert comparison["has_baseline"] is True
    assert comparison["baseline_count"] == 1
    assert comparison["baseline_avg_calls"] == 2
    assert comparison["current"]["physical_calls"] == 1
    assert comparison["call_delta_pct"] == -50.0
    assert comparison["baseline_avg_judge_calls"] == 1


def test_finalize_run_archives_current_run_idempotently(monkeypatch, tmp_path):
    llm_usage.reset_run()
    history_path = tmp_path / "usage.json"
    monkeypatch.setattr(llm_usage, "_HISTORY_PATH", history_path)
    monkeypatch.setenv("LLM_MAX_CALLS_PER_RUN", "0")

    llm_usage.reset_run("finalize-20260630-000001", mode="finalize", target_count=1)
    llm_usage.begin_call(label="generate_post", model="m", contents="hello")

    snapshot = llm_usage.finalize_run()
    llm_usage.finalize_run()

    history = json.loads(history_path.read_text(encoding="utf-8"))
    assert snapshot["run_id"] == "finalize-20260630-000001"
    assert len(history) == 1
    assert history[0]["run_id"] == "finalize-20260630-000001"
    assert history[0]["physical_calls"] == 1
    assert "ended_at" in history[0]


def test_resource_summary_exposes_budget_and_comparison(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_usage, "_HISTORY_PATH", tmp_path / "usage.json")
    monkeypatch.setenv("LLM_MAX_CALLS_PER_RUN", "4")

    llm_usage.reset_run("resource-20260630-000010", mode="resource-test", target_count=10)
    llm_usage.begin_call(label="generate_post", model="m", contents="a" * 10)
    llm_usage.begin_call(label="judge_post", model="m", contents="b" * 10)
    llm_usage.begin_call(label="analyze_trend", model="m", contents="c" * 10)

    llm_usage.reset_run("resource-20260630-000011", mode="resource-test", target_count=10)
    llm_usage.begin_call(label="generate_post", model="m", contents="d" * 10)
    llm_usage.begin_call(label="judge_post", model="m", contents="e" * 10)

    summary = llm_usage.resource_summary()

    assert summary["status"] == "good"
    assert summary["calls"] == 2
    assert summary["budget"] == 4
    assert summary["budget_ratio"] == 0.5
    assert summary["generate_calls"] == 1
    assert summary["judge_calls"] == 1
    assert summary["comparison"]["has_baseline"] is True
    assert summary["comparison"]["baseline_avg_calls"] == 3


def test_resource_summary_prefers_usage_tokens_when_available(monkeypatch, tmp_path):
    class Usage:
        prompt_token_count = 11
        candidates_token_count = 7
        total_token_count = 18

    class Response:
        usage_metadata = Usage()
        text = "ok"

    monkeypatch.setattr(llm_usage, "_HISTORY_PATH", tmp_path / "usage.json")
    monkeypatch.setenv("LLM_MAX_CALLS_PER_RUN", "0")

    llm_usage.reset_run("tokens-20260630-000001", mode="draft", target_count=1)
    call = llm_usage.begin_call(label="generate_post", model="m", contents="hello")
    llm_usage.record_success(call, Response())

    summary = llm_usage.resource_summary()

    assert summary["has_usage_tokens"] is True
    assert summary["prompt_tokens"] == 11
    assert summary["candidate_tokens"] == 7
    assert summary["total_tokens"] == 18
