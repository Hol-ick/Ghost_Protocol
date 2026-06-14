from ghost_protocol.application import stability


def test_billing_diagnostic_recommends_stop() -> None:
    state = {
        "run_mode": "infinite",
        "swarm_infinite": True,
        "ops_stop_on_billing_issue": True,
    }

    report = stability.evaluate_stability(
        state,
        logs=["429: Your prepayment credits are depleted."],
        intel_result={"raw_posts": [{"title": "source", "content": "body"}]},
    )

    assert report["stop_recommended"] is True
    assert any(item["code"] == "billing_stop" for item in report["findings"])


def test_refill_cycles_do_not_count_as_consecutive_bad_generation() -> None:
    cycles = [
        {"mode": "infinite", "summary": {"status": "bad", "requested": 10, "valid": 1}},
        {"mode": "infinite-refill", "summary": {"status": "bad", "requested": 1, "valid": 0}},
        {"mode": "infinite", "summary": {"status": "bad", "requested": 10, "valid": 0}},
    ]

    assert stability.consecutive_bad_generation_cycles(cycles) == 2


def test_feedback_alert_can_stop_infinite_run() -> None:
    state = {
        "run_mode": "infinite",
        "swarm_infinite": True,
        "ops_max_feedback_alerts": 2,
    }
    comments = [
        {"marker_feedback": 1, "content": "bot?"},
        {"marker_feedback": 1, "content": "AI?"},
    ]

    report = stability.evaluate_stability(
        state,
        ai_comments=comments,
        intel_result={"raw_posts": [{"title": "source", "content": "body"}]},
    )

    assert report["stop_recommended"] is True
    assert report["feedback"]["flagged"] == 2


def test_phase_inference_prefers_active_worker_state() -> None:
    assert stability.infer_run_phase({"intel_running": True}) == "reading"
    assert stability.infer_run_phase({"batch_generating": True}) == "generating"
    assert stability.infer_run_phase({"batch_generating": True, "_infinite_refill_round": 1}) == "refilling"
    assert stability.infer_run_phase({"swarm_running": True}) == "publishing"
    assert stability.infer_run_phase({"review_ready": True}) == "reviewing"


def test_format_stability_markdown_includes_findings() -> None:
    report = {
        "status": "critical",
        "phase": "publishing",
        "stop_recommended": True,
        "findings": [
            {
                "severity": "critical",
                "title": "발행 실패 누적",
                "action": "계정 상태를 확인하세요.",
                "stop": True,
            }
        ],
        "feedback": {"total": 3, "flagged": 1},
    }

    text = stability.format_stability_markdown(report)

    assert "## Stability" in text
    assert "발행 실패 누적" in text
    assert "3 total" in text
