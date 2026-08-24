"""Public data contracts for the local Web Studio worker runtime.

The browser-facing control plane should observe a run through these small
immutable value objects rather than reaching into a worker thread, queue, or
local persistence implementation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RunState(str, Enum):
    """Lifecycle states exposed by the local worker runtime."""

    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    STOPPING = "stopping"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"


class LocalWorkerError(RuntimeError):
    """Base class for errors raised by the runtime control surface."""


class ActiveRunError(LocalWorkerError):
    """Raised when a second run is requested while one is active."""


class RunNotFoundError(LocalWorkerError):
    """Raised when a requested run id is not known to the runtime."""


@dataclass(frozen=True, slots=True)
class RunSpec:
    """Input supplied to one local worker run.

    ``params`` is copied at construction time so callers cannot mutate the
    worker's input through a dictionary they continue to own.
    """

    mode: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        mode = str(self.mode or "").strip()
        if not mode:
            raise ValueError("RunSpec.mode must not be empty")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "params", dict(self.params or {}))


@dataclass(frozen=True, slots=True)
class RunEvent:
    """An ordered, replayable event emitted by a local worker run."""

    sequence: int
    kind: str
    message: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("RunEvent.sequence must be positive")
        kind = str(self.kind or "").strip()
        if not kind:
            raise ValueError("RunEvent.kind must not be empty")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "message", str(self.message or ""))
        object.__setattr__(self, "payload", dict(self.payload or {}))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation for API adapters."""

        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "message": self.message,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    """Current observable state of one run."""

    run_id: str
    state: RunState
    created_at: str
    updated_at: str
    mode: str
    progress: Mapping[str, Any] = field(default_factory=dict)
    last_event_sequence: int = 0
    error: str | None = None
    result: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.run_id or "").strip():
            raise ValueError("RunSnapshot.run_id must not be empty")
        object.__setattr__(self, "run_id", str(self.run_id))
        object.__setattr__(self, "mode", str(self.mode or ""))
        object.__setattr__(self, "progress", dict(self.progress or {}))
        object.__setattr__(self, "result", dict(self.result or {}))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation for API adapters."""

        return {
            "run_id": self.run_id,
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "mode": self.mode,
            "progress": dict(self.progress),
            "last_event_sequence": self.last_event_sequence,
            "error": self.error,
            "result": dict(self.result),
        }
