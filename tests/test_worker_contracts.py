import queue
import unittest

from ghost_protocol.application.worker_contracts import (
    BATCH_GEN_PARAMS,
    MSG_LOG,
    build_batch_gen_worker_kwargs,
    drain_queue,
    filter_batch_gen_config,
    worker_message,
)


class WorkerContractsTest(unittest.TestCase):
    def test_batch_filter_removes_posting_only_keys(self):
        config = {
            "topic": "topic",
            "headless": True,
            "wave_test_mode": True,
            "gallery_type": "mgallery",
            "style_profile": {"allow_long_laugh": True},
            "purpose_slot_enabled": False,
            "purpose_only": True,
            "is_refill": True,
            "rehearsal": True,
            "rehearsal_cycle": 2,
            "rehearsal_cycle_limit": 4,
            "rehearsal_anchor_posts": [{"title": "source"}],
            "rehearsal_anchor_topic": "anchor topic",
        }
        filtered = filter_batch_gen_config(config)
        self.assertEqual(filtered, {
            "topic": "topic",
            "gallery_type": "mgallery",
            "style_profile": {"allow_long_laugh": True},
            "purpose_slot_enabled": False,
            "purpose_only": True,
            "is_refill": True,
            "rehearsal": True,
            "rehearsal_cycle": 2,
            "rehearsal_cycle_limit": 4,
            "rehearsal_anchor_posts": [{"title": "source"}],
            "rehearsal_anchor_topic": "anchor topic",
        })
        self.assertNotIn("headless", filtered)

    def test_worker_kwargs_include_runtime_channels(self):
        kwargs = build_batch_gen_worker_kwargs(
            {"topic": "x", "headless": False},
            log_q="queue",
            stop_ev="event",
        )
        self.assertEqual(kwargs["topic"], "x")
        self.assertEqual(kwargs["log_q"], "queue")
        self.assertEqual(kwargs["stop_ev"], "event")
        self.assertFalse(kwargs["auto_refresh"])
        self.assertLessEqual(set(kwargs) - {"log_q", "stop_ev", "auto_refresh"}, BATCH_GEN_PARAMS)

    def test_worker_message_validates_type(self):
        self.assertEqual(worker_message(MSG_LOG, data="hello"), {"type": MSG_LOG, "data": "hello"})
        with self.assertRaises(ValueError):
            worker_message("unknown")

    def test_drain_queue_returns_available_items_and_empties_queue(self):
        q = queue.Queue()
        q.put("a")
        q.put("b")
        self.assertEqual(drain_queue(q), ["a", "b"])
        self.assertTrue(q.empty())


if __name__ == "__main__":
    unittest.main()
