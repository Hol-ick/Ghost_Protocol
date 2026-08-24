"""Adapters for running the existing local workers from Web Studio.

The adapter owns no UI state and never imports Streamlit at module import time.
Callers inject the legacy worker functions (the production app does this at
the worker boundary); tests can inject fixture workers without network access.
"""

from __future__ import annotations

import queue
import inspect
from collections.abc import Callable, Mapping
from typing import Any

from ghost_protocol.application import source_sampler
from ghost_protocol.application import studio_event_adapter
from ghost_protocol.application import worker_contracts


def _params(spec: Any) -> dict[str, Any]:
    value = getattr(spec, "params", spec)
    if not isinstance(value, Mapping):
        raise TypeError("job spec params must be a mapping")
    return dict(value)


class _EventQueue(queue.Queue):
    """Queue-compatible sink that forwards each worker message immediately."""

    def __init__(self, emit: Callable[[Any], None]) -> None:
        super().__init__()
        self._emit = emit
        self._sequence = 1
        self.terminal_seen = False

    def put(self, item: Any, block: bool = True, timeout: float | None = None) -> None:
        super().put(item, block=block, timeout=timeout)
        if isinstance(item, Mapping):
            event = studio_event_adapter.to_run_event(dict(item), sequence=self._sequence)
            self._sequence += 1
            if event.kind == "completed":
                self.terminal_seen = True
            self._emit(event)


Worker = Callable[..., Any]


class StudioJobRunner:
    """Run one of the existing worker implementations behind a stable seam."""

    def __init__(
        self,
        *,
        intel_worker: Worker | None = None,
        batch_worker: Worker | None = None,
        sample_collector: Worker | None = None,
    ) -> None:
        self._intel_worker = intel_worker
        self._batch_worker = batch_worker
        self._sample_collector = sample_collector or source_sampler.collect_samples

    @staticmethod
    def _resolve_app_worker(name: str) -> Worker:
        # Lazy import is intentional: importing this module must not execute
        # Streamlit's top-level app or load account/session state.
        from app import __dict__ as app_globals

        worker = app_globals.get(name)
        if not callable(worker):
            raise RuntimeError(f"production worker is unavailable: {name}")
        return worker

    def _worker(self, value: Worker | None, name: str) -> Worker:
        return value or self._resolve_app_worker(name)

    @staticmethod
    def _emit_done(emit: Callable[[Any], None], *, mode: str) -> None:
        message_type = (
            worker_contracts.MSG_INTEL_DONE
            if mode == "intel"
            else worker_contracts.MSG_BATCH_DONE
        )
        emit(studio_event_adapter.to_run_event({"type": message_type}))

    def run_intel(self, spec: Any, emit: Callable[[Any], None], stop_event: Any) -> None:
        """Run the existing trend/intel worker and forward its events."""

        params = _params(spec)
        sink = _EventQueue(emit)
        worker = self._worker(self._intel_worker, "_intel_worker")
        signature = inspect.signature(worker)
        accepts_stop = (
            "stop_ev" in signature.parameters
            or "stop_event" in signature.parameters
            or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
        )
        if accepts_stop:
            params["stop_ev"] = stop_event
        worker(log_q=sink, **params)
        if not sink.terminal_seen:
            self._emit_done(emit, mode="intel")

    def run_sample(self, spec: Any, emit: Callable[[Any], None], stop_event: Any) -> None:
        """Run read-only source sampling without exposing the scraper to UI code."""

        params = _params(spec)
        pages = max(1, min(int(params.pop("pages", 1) or 1), 5))
        comments = max(0, min(int(params.pop("comments_per_post", 3) or 0), 10))
        specs = params.pop("specs", params.pop("gallery_specs", []))
        if stop_event is not None and stop_event.is_set():
            return

        def progress(message: str) -> None:
            emit(
                studio_event_adapter.to_run_event(
                    {"type": worker_contracts.MSG_LOG, "data": str(message)}
                )
            )

        collector = self._sample_collector
        bundle = collector(
            specs,
            pages=pages,
            comments_per_post=comments,
            progress_callback=progress,
            **params,
        )
        if stop_event is not None and stop_event.is_set():
            return
        emit(
            studio_event_adapter.to_run_event(
                {"type": "sample_result", "data": bundle}
            )
        )
        emit(studio_event_adapter.to_run_event({"type": worker_contracts.MSG_DONE}))

    def run_rehearsal(self, spec: Any, emit: Callable[[Any], None], stop_event: Any) -> None:
        """Run batch generation in its no-post rehearsal mode."""

        params = _params(spec)
        params["rehearsal"] = True
        params.setdefault("infinite", False)
        params.setdefault("rehearsal_cycle", 1)
        params.setdefault("rehearsal_cycle_limit", 1)
        sink = _EventQueue(emit)
        worker = self._worker(self._batch_worker, "_batch_gen_worker_guarded")
        worker(log_q=sink, stop_ev=stop_event, **params)
        if not sink.terminal_seen:
            self._emit_done(emit, mode="rehearsal")


__all__ = ["StudioJobRunner"]
