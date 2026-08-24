"""Thread-backed local worker runtime used by the Web Studio control plane.

Only snapshots and ordered events cross this boundary.  The worker thread,
stop event, and any queue used by an adapter stay private to the runtime.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any
from uuid import uuid4

from ghost_protocol.application.local_worker_models import (
    ActiveRunError,
    LocalWorkerError,
    RunEvent,
    RunNotFoundError,
    RunSnapshot,
    RunSpec,
    RunState,
)


Runner = Callable[[RunSpec, Callable[..., None], threading.Event], None]

_ACTIVE_STATES = frozenset({RunState.QUEUED, RunState.RUNNING, RunState.STOPPING})
_TERMINAL_STATES = frozenset({RunState.SUCCEEDED, RunState.FAILED, RunState.STOPPED})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class _RunRecord:
    spec: RunSpec
    run_id: str
    created_at: str
    updated_at: str
    state: RunState = RunState.QUEUED
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    last_event_sequence: int = 0
    events: deque[RunEvent] = field(default_factory=deque)
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


class LocalWorkerRuntime:
    """Own at most one active worker and expose a replayable event journal."""

    def __init__(
        self,
        *,
        runner: Runner | Any,
        max_events: int = 500,
        run_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if runner is None:
            raise ValueError("runner is required")
        if not callable(runner) and not callable(getattr(runner, "run", None)):
            raise TypeError("runner must be callable or expose run(spec, emit, stop_event)")
        if int(max_events) < 1:
            raise ValueError("max_events must be at least 1")
        self._runner = runner
        self._max_events = int(max_events)
        self._run_id_factory = run_id_factory or (lambda: f"run-{uuid4().hex}")
        self._lock = threading.RLock()
        self._runs: dict[str, _RunRecord] = {}
        self._latest_run_id: str | None = None

    def start(self, spec: RunSpec) -> RunSnapshot:
        """Queue one run and return its initial snapshot.

        The worker starts asynchronously.  A caller may therefore observe
        ``queued`` briefly before the first ``started`` event is available.
        """

        if not isinstance(spec, RunSpec):
            raise TypeError("spec must be a RunSpec")
        with self._lock:
            active = next(
                (record for record in self._runs.values() if record.state in _ACTIVE_STATES),
                None,
            )
            if active is not None:
                raise ActiveRunError(f"run already active: {active.run_id}")

            run_id = str(self._run_id_factory()).strip()
            if not run_id:
                raise ValueError("run_id_factory returned an empty id")
            if run_id in self._runs:
                raise LocalWorkerError(f"duplicate run id: {run_id}")
            now = _utc_now()
            record = _RunRecord(
                spec=spec,
                run_id=run_id,
                created_at=now,
                updated_at=now,
                events=deque(maxlen=self._max_events),
            )
            self._runs[run_id] = record
            self._latest_run_id = run_id
            thread = threading.Thread(
                target=self._execute,
                args=(record,),
                name=f"ghost-protocol-worker-{run_id}",
                daemon=True,
            )
            record.thread = thread
            thread.start()
            return self._snapshot_locked(record)

    def snapshot(self, run_id: str | None = None) -> RunSnapshot:
        """Return a copy of one run, or the most recently created run."""

        with self._lock:
            resolved_id = run_id or self._latest_run_id
            record = self._get_record_locked(resolved_id)
            return self._snapshot_locked(record)

    def snapshots(self) -> list[RunSnapshot]:
        """Return snapshots in creation order for the control API."""

        with self._lock:
            return [self._snapshot_locked(record) for record in self._runs.values()]

    def events_after(
        self,
        run_id: str,
        after: int = 0,
        limit: int = 200,
    ) -> list[RunEvent]:
        """Return retained events whose sequence is greater than ``after``."""

        if int(after) < 0:
            raise ValueError("after must be non-negative")
        if int(limit) < 1:
            raise ValueError("limit must be positive")
        with self._lock:
            record = self._get_record_locked(run_id)
            return [
                event
                for event in record.events
                if event.sequence > int(after)
            ][: int(limit)]

    def stop(self, run_id: str) -> RunSnapshot:
        """Request cooperative stop; repeated calls are safe and idempotent."""

        with self._lock:
            record = self._get_record_locked(run_id)
            if record.state in _TERMINAL_STATES:
                return self._snapshot_locked(record)
            record.stop_event.set()
            if record.state is not RunState.STOPPING:
                record.state = RunState.STOPPING
                self._record_event_locked(
                    record,
                    kind="stopping",
                    message="Run stop requested",
                    payload={},
                )
            return self._snapshot_locked(record)

    def _execute(self, record: _RunRecord) -> None:
        with self._lock:
            if record.state in _TERMINAL_STATES:
                return
            if record.state is RunState.QUEUED:
                record.state = RunState.RUNNING
            if record.state is not RunState.STOPPING:
                self._record_event_locked(
                    record,
                    kind="started",
                    message="Run started",
                    payload={"mode": record.spec.mode},
                )
            should_stop_before_runner = record.stop_event.is_set()

        if should_stop_before_runner:
            with self._lock:
                self._finish_locked(
                    record,
                    state=RunState.STOPPED,
                    kind="stopped",
                    message="Run stopped before worker execution",
                    payload={},
                )
            return

        try:
            runner = getattr(self._runner, "run", self._runner)
            runner(record.spec, lambda *args, **kwargs: self._emit(record, *args, **kwargs), record.stop_event)
        except Exception as exc:
            with self._lock:
                if record.state not in _TERMINAL_STATES:
                    error = str(exc) or exc.__class__.__name__
                    self._finish_locked(
                        record,
                        state=RunState.FAILED,
                        kind="failed",
                        message=error,
                        payload={"error": error, "error_type": exc.__class__.__name__},
                    )
            return

        with self._lock:
            if record.state in _TERMINAL_STATES:
                return
            if record.stop_event.is_set() or record.state is RunState.STOPPING:
                self._finish_locked(
                    record,
                    state=RunState.STOPPED,
                    kind="stopped",
                    message="Run stopped",
                    payload={},
                )
            else:
                self._finish_locked(
                    record,
                    state=RunState.SUCCEEDED,
                    kind="succeeded",
                    message="Run completed",
                    payload={},
                )

    def _emit(self, record: _RunRecord, *args: Any, **kwargs: Any) -> RunEvent | None:
        kind, message, payload = self._normalise_emitted_event(args, kwargs)
        with self._lock:
            if record.state in _TERMINAL_STATES:
                return None
            return self._record_event_locked(
                record,
                kind=kind,
                message=message,
                payload=payload,
            )

    @staticmethod
    def _normalise_emitted_event(
        args: tuple[Any, ...],
        kwargs: Mapping[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        if not args and "kind" not in kwargs:
            raise TypeError("emit requires an event kind or mapping")
        if len(args) == 1 and isinstance(args[0], RunEvent):
            event = args[0]
            return event.kind, event.message, dict(event.payload)
        if len(args) == 1 and isinstance(args[0], Mapping):
            raw = dict(args[0])
            kind = str(raw.pop("kind", raw.pop("type", "log")))
            message = str(raw.pop("message", raw.pop("data", "")) or "")
            payload = raw.pop("payload", raw)
            return kind, message, dict(payload or {})

        kind = kwargs.get("kind", args[0] if args else "log")
        message = kwargs.get("message", args[1] if len(args) > 1 else "")
        payload = kwargs.get("payload", args[2] if len(args) > 2 else {})
        if len(args) > 3:
            raise TypeError("emit accepts kind, message, and payload")
        return str(kind), str(message or ""), dict(payload or {})

    def _record_event_locked(
        self,
        record: _RunRecord,
        *,
        kind: str,
        message: str,
        payload: Mapping[str, Any],
    ) -> RunEvent:
        record.last_event_sequence += 1
        now = _utc_now()
        event = RunEvent(
            sequence=record.last_event_sequence,
            kind=kind,
            message=message,
            payload=dict(payload),
            created_at=now,
        )
        record.events.append(event)
        record.updated_at = now
        if event.kind == "progress":
            record.progress = dict(event.payload)
        return event

    def _finish_locked(
        self,
        record: _RunRecord,
        *,
        state: RunState,
        kind: str,
        message: str,
        payload: Mapping[str, Any],
    ) -> None:
        record.state = state
        if state is RunState.FAILED:
            record.error = str(payload.get("error") or message)
        elif state is RunState.SUCCEEDED:
            record.result = dict(payload)
        self._record_event_locked(record, kind=kind, message=message, payload=payload)

    def _get_record_locked(self, run_id: str | None) -> _RunRecord:
        if not run_id or run_id not in self._runs:
            raise RunNotFoundError(f"unknown run: {run_id or '<latest>'}")
        return self._runs[run_id]

    @staticmethod
    def _snapshot_locked(record: _RunRecord) -> RunSnapshot:
        return RunSnapshot(
            run_id=record.run_id,
            state=record.state,
            created_at=record.created_at,
            updated_at=record.updated_at,
            mode=record.spec.mode,
            progress=dict(record.progress),
            last_event_sequence=record.last_event_sequence,
            error=record.error,
            result=dict(record.result),
        )


__all__ = [
    "ActiveRunError",
    "LocalWorkerRuntime",
    "RunNotFoundError",
]
