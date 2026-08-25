import unittest
from unittest.mock import patch

from ghost_protocol.ui.session_state import (
    apply_batch_message,
    apply_intel_message,
    apply_swarm_message,
    clear_test_summaries,
    init_session_state,
    reset_monitor_stats,
)
from ghost_protocol.application import worker_contracts
from ghost_protocol.ui.options import DEFAULT_GALLERY_TYPE_LABEL, DEFAULT_TONE_LABEL


class SessionStateDefaultsTest(unittest.TestCase):
    def test_preserves_existing_values(self):
        state = {"swarm_wave_count": 9}
        init_session_state(state)
        self.assertEqual(state["swarm_wave_count"], 9)

    def test_mutable_defaults_are_independent(self):
        first = {}
        second = {}
        init_session_state(first)
        init_session_state(second)
        first["swarm_log"].append("one")
        self.assertEqual(second["swarm_log"], [])

    def test_option_defaults_are_shared(self):
        state = {}
        init_session_state(state)
        self.assertEqual(state["target_tone_label"], DEFAULT_TONE_LABEL)
        self.assertEqual(state["intel_type_label"], DEFAULT_GALLERY_TYPE_LABEL)
        self.assertEqual(state["rehearsal_cycle_limit"], 3)
        self.assertEqual(state["rehearsal_runs"], [])

    def test_clear_test_summaries_can_reset_log_path(self):
        state = {
            "test_summaries": ["a"],
            "_test_wave_counter": 2,
            "_test_log_path": "logs/test.txt",
        }
        clear_test_summaries(state, reset_log_path=True)
        self.assertEqual(state["test_summaries"], [])
        self.assertEqual(state["_test_wave_counter"], 0)
        self.assertIsNone(state["_test_log_path"])

    def test_reset_monitor_stats_preserves_log_path(self):
        state = {
            "posts_success": 3,
            "posts_failed": 1,
            "swarm_log": ["x"],
            "swarm_preview_title": "title",
            "swarm_preview_content": "content",
            "test_summaries": ["summary"],
            "_test_wave_counter": 4,
            "_test_log_path": "logs/test.txt",
        }
        reset_monitor_stats(state)
        self.assertEqual(state["posts_success"], 0)
        self.assertEqual(state["posts_failed"], 0)
        self.assertEqual(state["swarm_log"], [])
        self.assertEqual(state["swarm_preview_title"], "")
        self.assertEqual(state["swarm_preview_content"], "")
        self.assertEqual(state["test_summaries"], [])
        self.assertEqual(state["_test_wave_counter"], 0)
        self.assertEqual(state["_test_log_path"], "logs/test.txt")

    def test_apply_swarm_message_updates_preview_stats_and_done(self):
        state = {
            "swarm_log": [],
            "posts_success": 0,
            "posts_failed": 0,
            "swarm_running": True,
            "swarm_queue": "queue",
            "swarm_stop_event": "event",
        }
        self.assertFalse(apply_swarm_message(state, worker_contracts.worker_message(worker_contracts.MSG_LOG, data="hello")))
        self.assertEqual(state["swarm_log"], ["hello"])
        apply_swarm_message(
            state,
            worker_contracts.worker_message(
                worker_contracts.MSG_PREVIEW,
                title="T",
                content="C",
                wave=2,
                status="ok",
            ),
        )
        self.assertEqual(state["swarm_preview_title"], "T")
        self.assertEqual(state["swarm_wave_current"], 2)
        apply_swarm_message(
            state,
            worker_contracts.worker_message(worker_contracts.MSG_STAT, success=1, fail=1),
        )
        self.assertEqual(state["posts_success"], 1)
        self.assertEqual(state["posts_failed"], 1)
        with patch("ghost_protocol.ui.session_state.llm_usage.finalize_run") as finalize:
            self.assertTrue(apply_swarm_message(state, worker_contracts.worker_message(worker_contracts.MSG_DONE)))
            finalize.assert_called_once_with()
        self.assertFalse(state["swarm_running"])
        self.assertIsNone(state["swarm_queue"])

    def test_apply_intel_message_updates_cache_without_file_write(self):
        state = {
            "intel_gallery_id": "abc",
            "intel_type_label": DEFAULT_GALLERY_TYPE_LABEL,
            "intel_cache": {},
            "intel_log": [],
            "intel_running": True,
            "intel_queue": "queue",
        }
        apply_intel_message(
            state,
            worker_contracts.worker_message(worker_contracts.MSG_INTEL_RESULT, data={"ok": True}, ts=10.0),
            save_last_cache=False,
        )
        self.assertEqual(state["intel_result"], {"ok": True})
        self.assertEqual(state["intel_cache"]["abc::mgallery"]["ts"], 10.0)
        with patch("ghost_protocol.ui.session_state.llm_usage.finalize_run") as finalize:
            self.assertTrue(apply_intel_message(state, worker_contracts.worker_message(worker_contracts.MSG_INTEL_DONE)))
            finalize.assert_called_once_with()
        self.assertFalse(state["intel_running"])
        self.assertIsNone(state["intel_queue"])

    def test_apply_batch_message_updates_progress_context_and_done(self):
        state = {
            "swarm_log": [],
            "_batch_gen_config": {},
            "batch_generating": True,
            "batch_gen_queue": "queue",
        }
        apply_batch_message(
            state,
            worker_contracts.worker_message(worker_contracts.MSG_BATCH_PROGRESS, wave=1, total=3),
        )
        self.assertEqual(state["swarm_wave_current"], 1)
        self.assertEqual(state["swarm_wave_total"], 3)
        state["_batch_gen_config"] = {"topic": "old"}
        apply_batch_message(
            state,
            worker_contracts.worker_message(
                worker_contracts.MSG_CONTEXT_UPDATED,
                topic="new",
                intel={"sentiment": "neutral"},
            ),
        )
        self.assertEqual(state["_batch_gen_config"]["topic"], "new")
        self.assertEqual(state["intel_result"], {"sentiment": "neutral"})
        with patch("ghost_protocol.ui.session_state.llm_usage.finalize_run") as finalize:
            self.assertTrue(
                apply_batch_message(
                    state,
                    worker_contracts.worker_message(worker_contracts.MSG_BATCH_DONE, scripts=[{"wave": 1}]),
                )
            )
            finalize.assert_called_once_with()
        self.assertEqual(state["review_scripts"], [{"wave": 1}])
        self.assertIsNone(state["_batch_fatal_error"])
        self.assertFalse(state["batch_generating"])
        self.assertIsNone(state["batch_gen_queue"])

    def test_batch_done_preserves_fatal_worker_error(self):
        state = {
            "swarm_log": [],
            "batch_generating": True,
            "batch_gen_queue": "queue",
        }
        with patch("ghost_protocol.ui.session_state.llm_usage.finalize_run"):
            self.assertTrue(
                apply_batch_message(
                    state,
                    worker_contracts.worker_message(
                        worker_contracts.MSG_BATCH_DONE,
                        scripts=[],
                        fatal_error="NameError: config is not defined",
                    ),
                )
            )
        self.assertEqual(
            state["_batch_fatal_error"],
            "NameError: config is not defined",
        )
        self.assertFalse(state["batch_generating"])


if __name__ == "__main__":
    unittest.main()
