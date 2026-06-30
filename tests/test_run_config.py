from ghost_protocol.application import run_config


def test_draft_run_keeps_requested_count_and_appends_guidance():
    setup = run_config.build_batch_run_setup(
        api_key="key",
        topic="briefing",
        guidance="write safely",
        requested_count=4,
        gallery_id="boardgame",
        gallery_type="minor",
        tone="dry",
        length="short",
        headless=True,
        infinite=False,
        rehearsal=False,
        style_profile={"laugh": "low"},
        composition_profile={"shape": "mixed"},
    )

    assert setup.run_mode == "draft"
    assert setup.actual_count == 4
    assert setup.worker_topic == "briefing\n\n[작문 지시]\nwrite safely"
    assert setup.batch_config["wave_count"] == 4
    assert setup.batch_config["briefing"] == "briefing"
    assert setup.batch_config["guidance"] == "write safely"
    assert setup.batch_config["headless"] is True
    assert setup.worker_kwargs["topic"] == setup.worker_topic
    assert "단일 묶음" in setup.initial_log_lines[0]


def test_infinite_run_forces_ten_and_sets_loop_log():
    setup = run_config.build_batch_run_setup(
        api_key="key",
        topic="topic",
        guidance="",
        requested_count=3,
        gallery_id="universe",
        gallery_type="minor",
        tone="neutral",
        length="short",
        headless=False,
        infinite=True,
        rehearsal=False,
    )

    assert setup.run_mode == "infinite"
    assert setup.actual_count == 10
    assert setup.batch_config["infinite"] is True
    assert setup.batch_config["wave_test_mode"] is False
    assert setup.worker_kwargs["infinite"] is True
    assert any("무한모드 시작" in line for line in setup.initial_log_lines)


def test_rehearsal_run_forces_ten_and_carries_anchor_posts():
    raw_posts = [{"title": "one"}, {"title": "two"}, "bad"]
    setup = run_config.build_batch_run_setup(
        api_key="key",
        topic="topic",
        guidance="guide",
        requested_count=2,
        gallery_id="universe",
        gallery_type="minor",
        tone="neutral",
        length="short",
        headless=False,
        infinite=False,
        rehearsal=True,
        rehearsal_cycle_limit=9,
        intel_result={"raw_posts": raw_posts},
    )

    assert setup.run_mode == "rehearsal"
    assert setup.actual_count == 10
    assert setup.rehearsal_cycle_limit <= 9
    assert setup.rehearsal_anchor_posts == [{"title": "one"}, {"title": "two"}]
    assert setup.batch_config["rehearsal"] is True
    assert setup.batch_config["infinite"] is False
    assert setup.worker_kwargs["rehearsal_anchor_posts"] == setup.rehearsal_anchor_posts
    assert any("리허설" in line for line in setup.initial_log_lines)
