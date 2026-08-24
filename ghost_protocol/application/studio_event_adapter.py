"""Translate legacy worker queue messages into Web Studio run events.

The Streamlit UI still consumes the original ``worker_contracts`` messages.
The local Web Studio runtime consumes the smaller, transport-neutral event
contract instead.  Keeping this translation in one module lets both clients
observe the same worker without teaching workers about either UI.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ghost_protocol.application import worker_contracts


@dataclass(frozen=True)
class _FallbackRunEvent:
    """Small compatibility value used while the runtime models are unavailable.

    Task 1 provides the canonical ``RunEvent`` model.  The fallback keeps this
    adapter importable in isolation (and is intentionally shaped identically)
    for downstream users that load the adapter during an incremental upgrade.
    """

    sequence: int = 1
    kind: str = "log"
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


_TYPE_TO_KIND: dict[str, str] = {
    worker_contracts.MSG_LOG: "log",
    worker_contracts.MSG_INTEL_LOG: "log",
    worker_contracts.MSG_PREVIEW: "preview",
    worker_contracts.MSG_STAT: "stat",
    worker_contracts.MSG_DONE: "completed",
    worker_contracts.MSG_INTEL_DONE: "completed",
    worker_contracts.MSG_BATCH_PROGRESS: "progress",
    worker_contracts.MSG_CONTEXT_UPDATED: "context",
    worker_contracts.MSG_BATCH_DONE: "completed",
    worker_contracts.MSG_INTEL_RESULT: "result",
    "sample_result": "result",
}


def _event_model() -> type[Any]:
    """Return the canonical runtime event model when Task 1 is present."""

    try:
        from ghost_protocol.application.local_worker_models import RunEvent
    except (ImportError, AttributeError):
        return _FallbackRunEvent
    return RunEvent


def _construct_event(
    *,
    kind: str,
    message: str,
    payload: Mapping[str, Any],
    sequence: int = 1,
) -> Any:
    model = _event_model()
    created_at = datetime.now(timezone.utc).isoformat()
    values = {
        "sequence": sequence,
        "kind": kind,
        "message": message,
        "payload": dict(payload),
        "created_at": created_at,
    }
    try:
        return model(**values)
    except (TypeError, ValueError):
        # A short-lived compatibility path for a model that uses a float
        # timestamp instead of the ISO string used by the public contract.
        values["created_at"] = datetime.now(timezone.utc).timestamp()
        try:
            return model(**values)
        except (TypeError, ValueError):
            # Only pass fields that the model declares.  This also permits
            # lightweight test doubles with a subset of the full contract.
            import inspect

            parameters = inspect.signature(model).parameters
            return model(**{key: value for key, value in values.items() if key in parameters})


def _payload_for_message(message: Mapping[str, Any]) -> dict[str, Any]:
    message_type = str(message.get("type") or "")
    if message_type in {
        worker_contracts.MSG_LOG,
        worker_contracts.MSG_INTEL_LOG,
    }:
        return {}
    if message_type in {worker_contracts.MSG_INTEL_RESULT, "sample_result"}:
        return {"data": message.get("data")}
    return {
        key: value
        for key, value in message.items()
        if key not in {"type", "data"}
    }


def to_run_event(message: dict, *, sequence: int = 1) -> Any:
    """Convert one legacy worker message into a ``RunEvent``.

    ``MSG_BATCH_PROGRESS`` deliberately retains only ``wave`` and ``total``
    in its payload, so consumers can use the event without knowing the queue
    message vocabulary.  Unknown message types are represented as ``message``
    events instead of being dropped; this protects forward compatibility.
    """

    if not isinstance(message, Mapping):
        raise TypeError("worker message must be a mapping")

    message_type = str(message.get("type") or "")
    kind = _TYPE_TO_KIND.get(message_type, "message")
    raw_data = message.get("data", "")
    text = str(raw_data if raw_data is not None else "")
    if message_type == worker_contracts.MSG_INTEL_RESULT:
        text = "분석 결과 수신"
    elif message_type == worker_contracts.MSG_BATCH_DONE:
        text = "배치 생성 완료"
    elif message_type == worker_contracts.MSG_INTEL_DONE:
        text = "트렌드 분석 완료"
    elif message_type == worker_contracts.MSG_DONE:
        text = "실행 완료"
    elif message_type and not text:
        text = message_type

    return _construct_event(
        kind=kind,
        message=text,
        payload=_payload_for_message(message),
        sequence=sequence,
    )


def to_worker_message(event: Any, *, mode: str = "rehearsal") -> dict[str, Any]:
    """Convert a Web Studio event back to a legacy queue message.

    Streamlit uses this bridge while it is being migrated.  ``mode`` is only
    needed to distinguish the two legacy completion messages; it never changes
    the worker implementation or its safety policy.
    """

    kind = str(getattr(event, "kind", "message") or "message")
    message = str(getattr(event, "message", "") or "")
    payload = dict(getattr(event, "payload", {}) or {})
    if kind == "log":
        return worker_contracts.worker_message(worker_contracts.MSG_LOG, data=message)
    if kind == "preview":
        return worker_contracts.worker_message(worker_contracts.MSG_PREVIEW, **payload)
    if kind == "stat":
        return worker_contracts.worker_message(worker_contracts.MSG_STAT, **payload)
    if kind == "progress":
        return worker_contracts.worker_message(worker_contracts.MSG_BATCH_PROGRESS, **payload)
    if kind == "context":
        return worker_contracts.worker_message(worker_contracts.MSG_CONTEXT_UPDATED, **payload)
    if kind == "result":
        return worker_contracts.worker_message(worker_contracts.MSG_INTEL_RESULT, data=payload.get("data"))
    if kind == "completed":
        if mode == "intel":
            return worker_contracts.worker_message(worker_contracts.MSG_INTEL_DONE)
        return worker_contracts.worker_message(worker_contracts.MSG_BATCH_DONE, **payload)
    return worker_contracts.worker_message(worker_contracts.MSG_LOG, data=message)


__all__ = ["to_run_event", "to_worker_message"]
