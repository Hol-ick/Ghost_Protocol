import unittest

from ghost_protocol.ui import options
from ghost_protocol.ui.session_state import (
    apply_pending_ai_briefing_topic,
    init_session_state,
    queue_pending_ai_briefing_topic,
)


class UiSessionStateTest(unittest.TestCase):
    def test_pending_ai_briefing_topic_applies_before_widgets(self):
        state = {}
        queue_pending_ai_briefing_topic(
            state,
            topic="브리핑 본문",
            gallery_id="universe",
            type_label="정규 게시판",
        )

        self.assertTrue(apply_pending_ai_briefing_topic(state))
        self.assertEqual(state["swarm_topic_input"], "브리핑 본문")
        self.assertEqual(state["target_gallery_id"], "universe")
        self.assertEqual(state["intel_gallery_id"], "universe")
        self.assertEqual(state["target_type_label"], "정규 게시판")
        self.assertEqual(state["intel_type_label"], "정규 게시판")
        self.assertNotIn("_pending_ai_briefing_topic", state)

    def test_pending_ai_briefing_topic_normalizes_missing_type(self):
        state = {
            "_pending_ai_briefing_topic": {
                "topic": "요약",
                "gallery_id": "baseball_new9",
            }
        }

        self.assertTrue(apply_pending_ai_briefing_topic(state))
        self.assertEqual(
            state["target_type_label"],
            options.DEFAULT_GALLERY_TYPE_LABEL,
        )

    def test_pending_ai_briefing_topic_noops_when_empty(self):
        state = {}

        self.assertFalse(apply_pending_ai_briefing_topic(state))
        self.assertEqual(state, {})

    def test_init_session_state_uses_independent_defaults(self):
        first = {}
        second = {}

        init_session_state(first)
        init_session_state(second)
        first["swarm_log"].append("line")

        self.assertEqual(second["swarm_log"], [])


if __name__ == "__main__":
    unittest.main()
