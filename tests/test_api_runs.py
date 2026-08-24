from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from ghost_protocol.api.main import create_app
from ghost_protocol.application.local_worker_models import RunSpec
from ghost_protocol.application.local_worker_runtime import LocalWorkerRuntime


def _wait_terminal(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        body = client.get(f"/v1/runs/{run_id}").json()
        if body["state"] in {"succeeded", "failed", "stopped"}:
            return body
        time.sleep(0.01)
    return client.get(f"/v1/runs/{run_id}").json()


def test_start_run_returns_snapshot_and_events() -> None:
    def runner(spec: RunSpec, emit, stop_event: threading.Event) -> None:
        emit("progress", "fixture progress", {"completed": 1, "total": 1})

    runtime = LocalWorkerRuntime(runner=runner)
    client = TestClient(create_app(runtime=runtime))

    response = client.post("/v1/runs", json={"mode": "sample", "params": {"pages": 1}})

    assert response.status_code == 202
    run_id = response.json()["run_id"]
    terminal = _wait_terminal(client, run_id)
    assert terminal["state"] == "succeeded"

    events_response = client.get(f"/v1/runs/{run_id}/events?after=0")
    assert events_response.status_code == 200
    events = events_response.json()["events"]
    assert [event["kind"] for event in events] == [
        "started",
        "progress",
        "succeeded",
    ]
    assert events[1]["payload"] == {"completed": 1, "total": 1}


def test_second_active_run_is_rejected_and_stop_is_idempotent() -> None:
    entered = threading.Event()
    release = threading.Event()

    def runner(spec: RunSpec, emit, stop_event: threading.Event) -> None:
        entered.set()
        release.wait(timeout=2)

    runtime = LocalWorkerRuntime(runner=runner)
    client = TestClient(create_app(runtime=runtime))
    first = client.post("/v1/runs", json={"mode": "sample"})
    assert first.status_code == 202
    run_id = first.json()["run_id"]
    assert entered.wait(timeout=1)

    second = client.post("/v1/runs", json={"mode": "sample"})
    assert second.status_code == 409
    assert second.json()["detail"] == "active_run"

    stopping = client.post(f"/v1/runs/{run_id}/stop")
    assert stopping.status_code == 200
    assert stopping.json()["state"] == "stopping"
    release.set()
    assert _wait_terminal(client, run_id)["state"] == "stopped"
    assert client.post(f"/v1/runs/{run_id}/stop").json()["state"] == "stopped"


def test_run_request_rejects_browser_credentials() -> None:
    runtime = LocalWorkerRuntime(runner=lambda spec, emit, stop_event: None)
    client = TestClient(create_app(runtime=runtime))

    response = client.post(
        "/v1/runs",
        json={"mode": "rehearsal", "params": {"api_key": "must-not-cross"}},
    )

    assert response.status_code == 422
    assert "local credential field" in response.text


def test_run_endpoints_return_not_found_and_cors_is_loopback_only() -> None:
    runtime = LocalWorkerRuntime(runner=lambda spec, emit, stop_event: None)
    client = TestClient(create_app(runtime=runtime))

    assert client.get("/v1/runs/missing").status_code == 404
    assert client.get("/v1/runs/missing/events").status_code == 404
    assert client.post("/v1/runs/missing/stop").status_code == 404

    allowed = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    pages_allowed = client.options(
        "/health",
        headers={
            "Origin": "https://hol-ick.github.io",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert pages_allowed.headers.get("access-control-allow-origin") == "https://hol-ick.github.io"

    denied = client.options(
        "/health",
        headers={
            "Origin": "https://example.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in denied.headers
