"""Contracts for background worker handoffs.

The Streamlit layer keeps extra UI/posting settings in the same config dict.
These helpers define what each worker actually accepts so future keys do not
accidentally break daemon threads.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


WorkerMessage = dict[str, Any]
WorkerMessageEmitter = Callable[[WorkerMessage], None]


BATCH_GEN_PARAMS: frozenset[str] = frozenset(
    {
        "api_key",
        "topic",
        "wave_count",
        "gallery_id",
        "gallery_type",
        "tone",
        "length",
        "infinite",
        "style_profile",
        "composition_profile",
        "purpose_slot_enabled",
        "purpose_only",
        "is_refill",
        "rehearsal",
        "rehearsal_cycle",
        "rehearsal_cycle_limit",
        "rehearsal_anchor_posts",
        "rehearsal_anchor_topic",
    }
)

MSG_LOG = "log"
MSG_PREVIEW = "preview"
MSG_STAT = "stat"
MSG_DONE = "done"
MSG_INTEL_LOG = "intel_log"
MSG_INTEL_RESULT = "intel_result"
MSG_INTEL_DONE = "intel_done"
MSG_BATCH_PROGRESS = "batch_progress"
MSG_CONTEXT_UPDATED = "context_updated"
MSG_BATCH_DONE = "batch_done"

KNOWN_MESSAGE_TYPES: frozenset[str] = frozenset(
    {
        MSG_LOG,
        MSG_PREVIEW,
        MSG_STAT,
        MSG_DONE,
        MSG_INTEL_LOG,
        MSG_INTEL_RESULT,
        MSG_INTEL_DONE,
        MSG_BATCH_PROGRESS,
        MSG_CONTEXT_UPDATED,
        MSG_BATCH_DONE,
    }
)


def filter_batch_gen_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return only kwargs accepted by the batch generation worker."""
    return {key: value for key, value in config.items() if key in BATCH_GEN_PARAMS}


def build_batch_gen_worker_kwargs(
    config: Mapping[str, Any],
    *,
    log_q: Any,
    stop_ev: Any,
    auto_refresh: bool = True,
) -> dict[str, Any]:
    """Build the exact kwargs payload for `_batch_gen_worker`."""
    return {
        **filter_batch_gen_config(config),
        "log_q": log_q,
        "stop_ev": stop_ev,
        "auto_refresh": auto_refresh,
    }


def worker_message(message_type: str, **payload: Any) -> WorkerMessage:
    """Build a queue message and fail fast for unknown message types."""
    if message_type not in KNOWN_MESSAGE_TYPES:
        raise ValueError(f"Unknown worker message type: {message_type}")
    return {"type": message_type, **payload}


def drain_queue(message_queue: Any) -> list[Any]:
    """Drain all currently available items from a Queue-like object."""
    items: list[Any] = []
    while True:
        try:
            items.append(message_queue.get_nowait())
        except Exception as exc:
            if exc.__class__.__name__ == "Empty":
                break
            raise
    return items
