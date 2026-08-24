from __future__ import annotations

import threading
import time

import pytest

from ghost_protocol.application.local_worker_models import RunSpec, RunState
from ghost_protocol.application.local_worker_runtime import (
    ActiveRunError,
    LocalWorkerRuntime,
    RunNotFoundError,
)


def _wait_for_state(runtime: LocalWorkerRuntime, run_id: str, state: RunState) -> object:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        snapshot = runtime.snapshot(run_id)
        if snapshot.state is state:
            return snapshot
        time.sleep(0.005)
    return runtime.snapshot(run_id)


def test_runtime_rejects_second_active_run():
    started = threading.Event()
    release = threading.Event()

    def blocking_fake_runner(spec, emit, stop_event):
        started.set()
        release.wait(timeout=2)

    runtime = LocalWorkerRuntime(runner=blocking_fake_runner)
    first = runtime.start(RunSpec(mode="sample", params={}))
    assert first.run_id
    assert started.wait(timeout=1)

    with pytest.raises(ActiveRunError):
        runtime.start(RunSpec(mode="sample", params={}))

    runtime.stop(first.run_id)
    release.set()
    assert _wait_for_state(runtime, first.run_id, RunState.STOPPED).state is RunState.STOPPED


def test_runtime_records_ordered_events_and_terminal_success():
    def fake_runner(spec, emit, stop_event):
        emit("progress", "첫 단계", {"completed": 1, "total": 2})
        emit({"kind": "log", "message": "fixture complete", "payload": {"source": "test"}})

    runtime = LocalWorkerRuntime(runner=fake_runner)
    started = runtime.start(RunSpec(mode="sample", params={"pages": 1}))

    snapshot = _wait_for_state(runtime, started.run_id, RunState.SUCCEEDED)
    assert snapshot.state is RunState.SUCCEEDED
    assert snapshot.progress == {"completed": 1, "total": 2}
    assert snapshot.last_event_sequence == 4

    events = runtime.events_after(started.run_id, after=0)
    assert [event.kind for event in events] == ["started", "progress", "log", "succeeded"]
    assert [event.sequence for event in events] == [1, 2, 3, 4]
    assert events[1].payload == {"completed": 1, "total": 2}


def test_runtime_stop_is_idempotent_and_preserves_terminal_snapshot():
    started = threading.Event()
    release = threading.Event()

    def blocking_fake_runner(spec, emit, stop_event):
        started.set()
        while not stop_event.is_set() and not release.is_set():
            time.sleep(0.005)

    runtime = LocalWorkerRuntime(runner=blocking_fake_runner)
    run = runtime.start(RunSpec(mode="sample", params={}))
    assert started.wait(timeout=1)

    stopping = runtime.stop(run.run_id)
    assert stopping.state is RunState.STOPPING
    stopping_again = runtime.stop(run.run_id)
    assert stopping_again.state is RunState.STOPPING
    release.set()

    terminal = _wait_for_state(runtime, run.run_id, RunState.STOPPED)
    assert terminal.state is RunState.STOPPED
    assert runtime.stop(run.run_id).state is RunState.STOPPED


def test_runtime_transitions_runner_exception_to_failed():
    def failing_fake_runner(spec, emit, stop_event):
        raise RuntimeError("fixture failure")

    runtime = LocalWorkerRuntime(runner=failing_fake_runner)
    run = runtime.start(RunSpec(mode="sample", params={}))

    terminal = _wait_for_state(runtime, run.run_id, RunState.FAILED)
    assert terminal.state is RunState.FAILED
    assert terminal.error == "fixture failure"
    events = runtime.events_after(run.run_id, after=0)
    assert events[-1].kind == "failed"
    assert events[-1].payload == {"error": "fixture failure", "error_type": "RuntimeError"}


def test_runtime_keeps_only_recent_events_but_cursor_is_monotonic():
    def noisy_fake_runner(spec, emit, stop_event):
        for index in range(4):
            emit("log", f"event-{index}")

    runtime = LocalWorkerRuntime(runner=noisy_fake_runner, max_events=3)
    run = runtime.start(RunSpec(mode="sample", params={}))
    terminal = _wait_for_state(runtime, run.run_id, RunState.SUCCEEDED)

    assert terminal.last_event_sequence == 6
    retained = runtime.events_after(run.run_id, after=0)
    assert [event.sequence for event in retained] == [4, 5, 6]
    assert [event.kind for event in runtime.events_after(run.run_id, after=4)] == ["log", "succeeded"]


def test_runtime_raises_for_unknown_run():
    runtime = LocalWorkerRuntime(runner=lambda spec, emit, stop_event: None)

    with pytest.raises(RunNotFoundError):
        runtime.snapshot("missing")
    with pytest.raises(RunNotFoundError):
        runtime.events_after("missing")
    with pytest.raises(RunNotFoundError):
        runtime.stop("missing")
