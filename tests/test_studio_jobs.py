from __future__ import annotations

import threading

from ghost_protocol.application import studio_event_adapter, worker_contracts
from ghost_protocol.application.run_config import BatchRunSetup, build_studio_job_params
from ghost_protocol.application.studio_jobs import StudioJobRunner


def test_studio_event_adapter_preserves_worker_message_type():
    event = studio_event_adapter.to_run_event(
        {"type": worker_contracts.MSG_BATCH_PROGRESS, "wave": 2, "total": 10}
    )
    assert event.kind == "progress"
    assert event.payload == {"wave": 2, "total": 10}


def test_rehearsal_runner_forwards_fixture_events_and_stop_event():
    seen: dict[str, object] = {}

    def fixture_worker(*, log_q, stop_ev, **kwargs):
        seen["stop_ev"] = stop_ev
        seen["kwargs"] = kwargs
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_LOG, data="fixture start"))
        log_q.put(
            worker_contracts.worker_message(
                worker_contracts.MSG_BATCH_PROGRESS,
                wave=1,
                total=10,
            )
        )
        log_q.put(
            worker_contracts.worker_message(
                worker_contracts.MSG_BATCH_DONE,
                scripts=[{"wave": 1, "title": "fixture"}],
            )
        )

    stop_event = threading.Event()
    events = []
    StudioJobRunner(batch_worker=fixture_worker).run_rehearsal(
        {"topic": "test", "rehearsal_cycle_limit": 3},
        events.append,
        stop_event,
    )

    assert [event.kind for event in events] == ["log", "progress", "completed"]
    assert seen["stop_ev"] is stop_event
    assert seen["kwargs"]["rehearsal"] is True
    assert seen["kwargs"]["infinite"] is False
    assert seen["kwargs"]["rehearsal_cycle_limit"] == 3


def test_intel_runner_adds_completion_when_legacy_fixture_omits_it():
    def fixture_worker(*, log_q, **kwargs):
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_INTEL_LOG, data="read"))

    events = []
    StudioJobRunner(intel_worker=fixture_worker).run_intel(
        {"api_key": "fixture", "gallery_id": "demo", "gallery_type": "mgallery", "pages": 1},
        events.append,
        threading.Event(),
    )

    assert [event.kind for event in events] == ["log", "completed"]
    assert events[0].message == "read"


def test_intel_runner_passes_stop_event_when_worker_accepts_it():
    seen: dict[str, object] = {}

    def fixture_worker(*, log_q, stop_ev, **kwargs):
        seen["stop_ev"] = stop_ev

    stop_event = threading.Event()
    StudioJobRunner(intel_worker=fixture_worker).run_intel(
        {"api_key": "fixture", "gallery_id": "demo", "gallery_type": "mgallery", "pages": 1},
        lambda event: None,
        stop_event,
    )

    assert seen["stop_ev"] is stop_event


def test_sample_runner_is_read_only_and_emits_result():
    calls: dict[str, object] = {}

    def fixture_collector(specs, *, pages, comments_per_post, progress_callback):
        calls.update(
            specs=specs,
            pages=pages,
            comments_per_post=comments_per_post,
        )
        progress_callback("fixture sample")
        return {"items": [{"ok": True}]}

    events = []
    StudioJobRunner(sample_collector=fixture_collector).run_sample(
        {"specs": ["demo"], "pages": 2, "comments_per_post": 3},
        events.append,
        threading.Event(),
    )

    assert [event.kind for event in events] == ["log", "result", "completed"]
    assert events[1].payload == {"data": {"items": [{"ok": True}]}}
    assert calls == {"specs": ["demo"], "pages": 2, "comments_per_post": 3}


def test_build_studio_job_params_excludes_ui_batch_config():
    setup = BatchRunSetup(
        run_mode="rehearsal",
        actual_count=10,
        worker_topic="topic",
        run_detail="",
        cycle_start_detail="",
        prompt_version={},
        batch_config={"api_key": "secret", "wave_interval_min": 1},
        worker_kwargs={"topic": "topic", "wave_count": 10, "rehearsal": True},
        initial_log_lines=[],
        rehearsal_cycle_limit=3,
        rehearsal_anchor_posts=[],
        rehearsal_anchor_topic="topic",
    )
    params = build_studio_job_params(setup, mode="rehearsal")
    assert params == {
        "topic": "topic",
        "wave_count": 10,
        "rehearsal": True,
        "infinite": False,
        "rehearsal_cycle": 1,
        "rehearsal_cycle_limit": 3,
    }
    assert "wave_interval_min" not in params
