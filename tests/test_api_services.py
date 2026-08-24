import unittest
from pydantic import ValidationError

from ghost_protocol.api.schemas import (
    CommunityAnalyzeRequest,
    ReplyDraftRequest,
    ThreadAnalyzeRequest,
)
from ghost_protocol.api import services


class ApiServicesTest(unittest.TestCase):
    def test_health_declares_draft_only_safety_contract(self):
        result = services.health()
        self.assertEqual(result.status, "ok")
        self.assertFalse(result.safety.posting_supported)
        self.assertIn("automatic_posting", result.safety.disallowed_actions)

    def test_keyword_only_community_analysis_uses_injected_snapshot(self):
        request = CommunityAnalyzeRequest(
            community_id="sample",
            use_llm=False,
            snapshot={
                "gallery_id": "sample",
                "gallery_type": "mgallery",
                "titles": ["rate cut rally", "rate cut debate"],
                "comments": ["rally needs evidence", "rate is not enough"],
                "authors": ["a", "b"],
                "raw_posts": [{"post_no": "1"}],
                "ai_post_count": 0,
                "total_post_count": 2,
            },
        )

        result = services.analyze_community_signal(request)

        self.assertEqual(result.community_id, "sample")
        self.assertIn("rate", result.analysis["top_keywords"])
        self.assertEqual(result.snapshot_stats["title_count"], 2)
        self.assertFalse(result.safety.posting_supported)

    def test_thread_analysis_clusters_rebuttals_and_questions(self):
        request = ThreadAnalyzeRequest(
            community_id="sample",
            post_no="10",
            title="Market will only go up",
            content="Liquidity is improving. That means risk assets win.",
            comments=[
                "But where is the evidence?",
                "agree with this",
                "why would rates not matter?",
            ],
            fetch_live=False,
        )

        result = services.analyze_thread(request)
        clusters = {cluster.label: cluster.count for cluster in result.comment_clusters}

        self.assertEqual(result.post_no, "10")
        self.assertGreaterEqual(clusters.get("rebuttal", 0), 1)
        self.assertGreaterEqual(clusters.get("question", 0), 1)
        self.assertTrue(result.key_counterpoints)

    def test_reply_draft_keeps_human_review_boundary(self):
        analysis = services.analyze_thread(
            ThreadAnalyzeRequest(
                community_id="sample",
                post_no="10",
                title="Market will only go up",
                comments=["But where is the evidence?"],
                fetch_live=False,
            )
        )
        request = ReplyDraftRequest(analysis=analysis, intent="logical_rebuttal")

        result = services.build_reply_draft(request)

        self.assertTrue(result.draft)
        self.assertTrue(result.needs_human_review)
        self.assertFalse(result.posting_supported)
        self.assertIn("But where is the evidence?", result.used_counterpoints)

    def test_reply_draft_request_requires_thread_or_analysis(self):
        with self.assertRaises(ValidationError):
            ReplyDraftRequest()


if __name__ == "__main__":
    unittest.main()
