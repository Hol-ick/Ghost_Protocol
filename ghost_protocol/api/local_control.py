"""Local-only control surface for the Web Studio worker runtime."""

from __future__ import annotations

import os
from collections.abc import Callable
from threading import Event
from typing import Any

from ghost_protocol.application.local_worker_models import RunSpec
from ghost_protocol.application.local_worker_runtime import LocalWorkerRuntime
from ghost_protocol.application.studio_jobs import StudioJobRunner


class LocalStudioRunner:
    """Dispatch one browser-safe run to the existing local worker adapters."""

    def __init__(self, *, jobs: StudioJobRunner | None = None) -> None:
        self.jobs = jobs or StudioJobRunner()

    def run(self, spec: RunSpec, emit: Callable[..., Any], stop_event: Event) -> None:
        params = dict(spec.params)
        if spec.mode in {"intel", "rehearsal"}:
            # The browser never supplies credentials.  Existing workers read
            # the local process environment through this private bridge.
            params["api_key"] = os.getenv("GEMINI_API_KEY", "").strip()
        local_spec = RunSpec(mode=spec.mode, params=params)
        if spec.mode == "sample":
            self.jobs.run_sample(local_spec, emit, stop_event)
        elif spec.mode == "intel":
            self.jobs.run_intel(local_spec, emit, stop_event)
        elif spec.mode == "rehearsal":
            self.jobs.run_rehearsal(local_spec, emit, stop_event)
        else:  # defensive guard for callers bypassing Pydantic validation
            raise ValueError(f"unsupported local run mode: {spec.mode}")


_runtime: LocalWorkerRuntime | None = None


def get_runtime() -> LocalWorkerRuntime:
    """Return the process-local singleton without starting a worker."""

    global _runtime
    if _runtime is None:
        _runtime = LocalWorkerRuntime(runner=LocalStudioRunner())
    return _runtime


def set_runtime(runtime: LocalWorkerRuntime | None) -> None:
    """Replace the singleton for fixture tests or an embedding host."""

    global _runtime
    _runtime = runtime


__all__ = ["LocalStudioRunner", "get_runtime", "set_runtime"]
