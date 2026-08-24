from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from ghost_protocol.api.main import create_app
from ghost_protocol.application.local_worker_models import RunSpec
from ghost_protocol.application.local_worker_runtime import LocalWorkerRuntime


def test_fixture_control_plane_preserves_run_and_event_sequence() -> None:
    def fixture_runner(spec: RunSpec, emit, stop_event: threading.Event) -> None:
        emit("progress", "fixture source read", {"completed": 1, "total": 2})
        emit("insight", "fixture signal ready", {"signal_count": 2})

    client = TestClient(create_app(runtime=LocalWorkerRuntime(runner=fixture_runner)))
    start = client.post("/v1/runs", json={"mode": "sample", "params": {"fixture": True}})
    assert start.status_code == 202
    run_id = start.json()["run_id"]

    deadline = time.monotonic() + 2
    snapshot = start.json()
    while snapshot["state"] not in {"succeeded", "failed", "stopped"} and time.monotonic() < deadline:
        snapshot = client.get(f"/v1/runs/{run_id}").json()
        time.sleep(0.01)

    page = client.get(f"/v1/runs/{run_id}/events?after=0&limit=200").json()
    assert snapshot["run_id"] == run_id
    assert snapshot["last_event_sequence"] == 4
    assert [event["sequence"] for event in page["events"]] == [1, 2, 3, 4]
    assert [event["kind"] for event in page["events"]] == [
        "started",
        "progress",
        "insight",
        "succeeded",
    ]
    assert page["events"][1]["payload"] == {"completed": 1, "total": 2}
    assert page["events"][2]["payload"] == {"signal_count": 2}

    resumed = client.get(f"/v1/runs/{run_id}/events?after=2&limit=200").json()
    assert [event["sequence"] for event in resumed["events"]] == [3, 4]
