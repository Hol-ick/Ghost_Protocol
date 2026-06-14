import unittest

from ghost_protocol.ui.intel_view_model import (
    build_ai_occupation_view,
    build_raw_post_debug_rows,
    keyword_chart_cache_key,
    raw_post_debug_caption,
    sentiment_css_class,
)


class IntelViewModelTest(unittest.TestCase):
    def test_sentiment_css_class_matches_keywords(self):
        self.assertEqual(sentiment_css_class("공포 확산"), "intel-sentiment-panic")
        self.assertEqual(sentiment_css_class("분노와 공격"), "intel-sentiment-hostile")
        self.assertEqual(sentiment_css_class("냉소 분위기"), "intel-sentiment-mock")
        self.assertEqual(sentiment_css_class("긍정 반응"), "intel-sentiment-friendly")
        self.assertEqual(sentiment_css_class("보통"), "intel-sentiment-neutral")

    def test_ai_occupation_uses_db_marked_posts_and_stats(self):
        view = build_ai_occupation_view(
            raw_posts=[
                {"post_no": "1", "is_bot": False},
                {"post_no": "2", "is_bot": True},
                {"post_no": "3", "is_bot": False},
            ],
            stats={"ai_post_count": 1, "total_post_count": 5},
            ai_post_nos={"1"},
        )
        self.assertEqual(view.ai_count, 2)
        self.assertEqual(view.total_count, 5)
        self.assertEqual(view.human_count, 3)
        self.assertEqual(view.pct_label, "40.0%")
        self.assertEqual(view.ratio_label, "2 / 5개")
        self.assertEqual(view.pct_color, "#FFBF00")

    def test_ai_occupation_empty_state_labels_no_data(self):
        view = build_ai_occupation_view([], {}, set())
        self.assertEqual(view.bar_width, "0%")
        self.assertEqual(view.pct_label, "—")
        self.assertEqual(view.ratio_label, "데이터 없음")

    def test_keyword_chart_cache_key_is_stable_for_same_payload(self):
        payload = {"top_keywords": ["a", "b"], "keyword_counts": {"a": 2}}
        self.assertEqual(keyword_chart_cache_key(payload), keyword_chart_cache_key(dict(payload)))

    def test_raw_post_debug_rows_mark_db_and_inline_bots(self):
        rows = build_raw_post_debug_rows(
            [
                {"post_no": "1", "title": "a" * 60, "author": "alice", "is_bot": False},
                {"post_no": "2", "title": "normal", "author": "bot", "is_bot": True},
                {"post_no": "3", "title": "human", "author": "carol", "is_bot": False},
            ],
            {"1"},
        )
        self.assertEqual(rows[0]["제목"], "a" * 45)
        self.assertEqual(rows[0]["🤖 봇"], "✅ BOT")
        self.assertEqual(rows[1]["🤖 봇"], "✅ BOT")
        self.assertEqual(rows[2]["🤖 봇"], "—")

    def test_raw_post_debug_caption_contains_counts_and_gallery_ids(self):
        caption = raw_post_debug_caption(
            ai_post_nos_count=3,
            intel_gallery_id="intel",
            target_gallery_id="target",
            raw_post_count=10,
        )
        self.assertIn("3개", caption)
        self.assertIn("`intel`", caption)
        self.assertIn("`target`", caption)
        self.assertIn("10개", caption)


if __name__ == "__main__":
    unittest.main()
