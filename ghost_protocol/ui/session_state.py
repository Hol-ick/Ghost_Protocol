"""Session state defaults for the Streamlit dashboard."""

from __future__ import annotations

import time
from collections.abc import MutableMapping
from copy import deepcopy

from ghost_protocol.application import operator_settings
from ghost_protocol.application import worker_contracts
from ghost_protocol.ui import intel_cache
from ghost_protocol.ui import options


SESSION_DEFAULTS: dict = {
    "swarm_log": [],
    "swarm_preview_title": "",
    "swarm_preview_content": "",
    "swarm_wave_current": 0,
    "swarm_wave_total": 0,
    "posts_success": 0,
    "posts_failed": 0,
    "last_fired": False,
    "swarm_running": False,
    "swarm_queue": None,
    "swarm_stop_event": None,
    "swarm_infinite": False,
    "batch_generating": False,
    "batch_gen_queue": None,
    "batch_gen_stop_event": None,
    "review_scripts": [],
    "review_ready": False,
    "_batch_gen_config": {},
    "_show_copy_box": False,
    "_last_batch_log": [],
    "_infinite_refill_scripts": [],
    "_infinite_refill_round": 0,
    "intel_running": False,
    "intel_queue": None,
    "intel_log": [],
    "intel_result": None,
    "intel_cache": {},
    "_intel_fig": None,
    "_intel_fig_key": None,
    "target_tone_label": options.DEFAULT_TONE_LABEL,
    "target_length": options.DEFAULT_LENGTH_LABEL,
    "target_headless": True,
    "target_gallery_id": "",
    "target_type_label": options.DEFAULT_GALLERY_TYPE_LABEL,
    "swarm_topic_input": "",
    "swarm_guidance_input": "",
    "swarm_wave_count": 3,
    "wave_interval_min": 1,
    "wave_interval_max": 3,
    "publish_interval_minutes": 3,
    "gemini_call_min_interval_sec": 1.5,
    "gemini_call_jitter_sec": 0.5,
    "wave_test_mode": False,
    "rehearsal_cycle_limit": 3,
    "rehearsal_runs": [],
    "ai_disclosure_enabled": False,
    "ai_disclosure_marker": operator_settings.DEFAULT_PUBLIC_AI_MARKER,
    "ai_comment_watch_limit": operator_settings.DEFAULT_AI_COMMENT_WATCH_LIMIT,
    "test_summaries": [],
    "_test_wave_counter": 0,
    "_test_log_path": None,
    "_rehearsal_complete": False,
    "run_id": "",
    "run_started_at": None,
    "run_mode": "idle",
    "run_gallery_id": "",
    "run_target_count": 0,
    "run_timeline": [],
    "run_cycles": [],
    "run_prompt_versions": [],
    "ops_max_infinite_cycles": 24,
    "ops_max_consecutive_bad_cycles": 3,
    "ops_max_publish_failures": 3,
    "ops_max_feedback_alerts": 3,
    "ops_stop_on_billing_issue": True,
    "ops_stop_on_empty_source": True,
    "_ops_last_stop_reason": "",
    "intel_gallery_id": "",
    "intel_type_label": options.DEFAULT_GALLERY_TYPE_LABEL,
    "intel_pages": 3,
    "sample_gallery_ids": "",
    "sample_gallery_type": options.DEFAULT_GALLERY_TYPE_LABEL,
    "sample_pages": 1,
    "sample_comments_per_post": 3,
    "sample_crawl_result": None,
    "sample_analysis_result": None,
    "sample_crawl_log": [],
    "sample_crawl_running": False,
    "_sample_log_focus": False,
    "_db_reset_confirm": False,
}


def init_session_state(session_state: MutableMapping) -> None:
    """Populate missing session keys with independent default values."""
    for key, value in SESSION_DEFAULTS.items():
        if key not in session_state:
            session_state[key] = deepcopy(value)


def apply_pending_ai_briefing_topic(session_state: MutableMapping) -> bool:
    """Apply a queued briefing topic before keyed Streamlit widgets are created."""
    pending = session_state.pop("_pending_ai_briefing_topic", None)
    if not pending:
        return False

    type_label = options.normalize_gallery_type_label(
        pending.get("type_label", options.DEFAULT_GALLERY_TYPE_LABEL)
    )
    gallery_id = pending.get("gallery_id", "")

    session_state["swarm_topic_input"] = pending.get("topic", "")
    session_state["swarm_guidance_input"] = pending.get("guidance", "")
    session_state["target_gallery_id"] = gallery_id
    session_state["target_type_label"] = type_label
    session_state["intel_gallery_id"] = gallery_id
    session_state["intel_type_label"] = type_label
    return True


def queue_pending_ai_briefing_topic(
    session_state: MutableMapping,
    *,
    topic: str,
    guidance: str = "",
    gallery_id: str,
    type_label: str,
) -> None:
    """Queue a briefing topic for the next full app rerun."""
    session_state["_pending_ai_briefing_topic"] = {
        "topic": topic,
        "guidance": guidance,
        "gallery_id": gallery_id,
        "type_label": type_label,
    }


def clear_test_summaries(session_state: MutableMapping, *, reset_log_path: bool) -> None:
    """Clear test-mode summary state while preserving caller-chosen log behavior."""
    session_state["test_summaries"] = []
    session_state["_test_wave_counter"] = 0
    if reset_log_path:
        session_state["_test_log_path"] = None


def reset_monitor_stats(session_state: MutableMapping) -> None:
    """Reset the live monitor counters and transient preview state."""
    session_state["posts_success"] = 0
    session_state["posts_failed"] = 0
    session_state["swarm_log"] = []
    session_state["swarm_preview_title"] = ""
    session_state["swarm_preview_content"] = ""
    clear_test_summaries(session_state, reset_log_path=False)


def apply_intel_message(
    session_state: MutableMapping,
    message: dict,
    *,
    save_last_cache: bool = True,
) -> bool:
    """Apply one Intel worker queue message. Returns True when the worker is done."""
    message_type = message.get("type")
    if message_type == worker_contracts.MSG_INTEL_LOG:
        session_state.setdefault("intel_log", []).append(message["data"])
    elif message_type == worker_contracts.MSG_INTEL_RESULT:
        data = message["data"]
        session_state["intel_result"] = data
        key = intel_cache.cache_key(
            session_state.get("intel_gallery_id", ""),
            session_state.get("intel_type_label", options.DEFAULT_GALLERY_TYPE_LABEL),
        )
        session_state.setdefault("intel_cache", {})[key] = {
            "result": data,
            "ts": message.get("ts", time.time()),
        }
        session_state["_intel_fig_key"] = None
        if save_last_cache:
            intel_cache.save_last_topic_cache(
                result=data,
                gallery_id=session_state.get("intel_gallery_id", ""),
                type_label=session_state.get(
                    "intel_type_label",
                    options.DEFAULT_GALLERY_TYPE_LABEL,
                ),
                ts=message.get("ts"),
            )
    elif message_type == worker_contracts.MSG_INTEL_DONE:
        session_state["intel_running"] = False
        session_state["intel_queue"] = None
        return True
    return False


def apply_swarm_message(session_state: MutableMapping, message: dict) -> bool:
    """Apply one posting/swarm queue message. Returns True when the worker is done."""
    message_type = message.get("type")
    if message_type == worker_contracts.MSG_LOG:
        session_state.setdefault("swarm_log", []).append(message["data"])
    elif message_type == worker_contracts.MSG_PREVIEW:
        session_state["swarm_preview_title"] = message["title"]
        session_state["swarm_preview_content"] = message["content"]
        session_state["swarm_wave_current"] = message["wave"]
    elif message_type == worker_contracts.MSG_STAT:
        session_state["posts_success"] = session_state.get("posts_success", 0) + message.get("success", 0)
        session_state["posts_failed"] = session_state.get("posts_failed", 0) + message.get("fail", 0)
    elif message_type == worker_contracts.MSG_DONE:
        session_state["swarm_running"] = False
        session_state["swarm_queue"] = None
        session_state["swarm_stop_event"] = None
        return True
    return False


def apply_batch_message(session_state: MutableMapping, message: dict) -> bool:
    """Apply one batch generation queue message. Returns True on batch completion."""
    message_type = message.get("type")
    if message_type == worker_contracts.MSG_LOG:
        session_state.setdefault("swarm_log", []).append(message["data"])
    elif message_type == worker_contracts.MSG_BATCH_PROGRESS:
        session_state["swarm_wave_current"] = message["wave"]
        session_state["swarm_wave_total"] = message["total"]
    elif message_type == worker_contracts.MSG_CONTEXT_UPDATED:
        fresh_intel = message.get("intel")
        if fresh_intel:
            session_state["intel_result"] = fresh_intel
        config = session_state.get("_batch_gen_config")
        if config and message.get("topic"):
            config["topic"] = message["topic"]
    elif message_type == worker_contracts.MSG_BATCH_DONE:
        session_state["review_scripts"] = message["scripts"]
        session_state["_batch_fatal_error"] = message.get("fatal_error")
        session_state["batch_generating"] = False
        session_state["batch_gen_queue"] = None
        session_state["_last_batch_log"] = list(session_state.get("swarm_log", []))
        return True
    return False
