import unittest

from ghost_protocol.application import observability


class ObservabilityTest(unittest.TestCase):
    def test_classifies_billing_and_rate_limit_logs(self):
        logs = [
            "⚠️ Rate Limit (429) — Gemini API Rate Limit 초과",
            "message=Your prepayment credits are depleted.",
        ]

        diagnostics = observability.classify_gemini_logs(logs)
        codes = {item["code"] for item in diagnostics}

        self.assertIn("billing_depleted", codes)
        self.assertIn("rate_limit", codes)

    def test_does_not_report_model_not_found_from_loose_words(self):
        logs = [
            "Model quality note: response contract is fine.",
            "source body was not found in the snapshot.",
        ]

        diagnostics = observability.classify_gemini_logs(logs)
        codes = {item["code"] for item in diagnostics}

        self.assertNotIn("model_not_found", codes)

    def test_summarizes_draft_success_and_failures(self):
        scripts = [
            {"title": "목성 중력으로 먼지 모이는 거", "content": "이거 계산 가능함?"},
            {
                "title": "목성 중력으로 먼지 모이는 거",
                "content": "같은 제목",
            },
            {
                "_failed": True,
                "_failure_reason": "near-duplicate",
                "_failure_stage": "post_generation_validation",
            },
        ]

        summary = observability.summarize_drafts(
            scripts,
            gallery_id="universe",
            target_count=4,
        )

        self.assertEqual(summary["valid"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["requested"], 4)
        self.assertIn("목성 중력으로 먼지 모이는 거", summary["duplicate_titles"])
        self.assertEqual(summary["failure_reasons"][0][0], "near-duplicate")

    def test_summarizes_comment_candidate_visibility(self):
        scripts = [
            {
                "title": "T1",
                "content": "C1",
                "target_comments": [
                    {"post_no": "1", "comment": "public"},
                    {"post_no": "2", "comment": "rehearsal", "simulation_only": True},
                    {"post_no": "3", "comment": "ai", "is_ai_post": True},
                ],
            }
        ]

        summary = observability.summarize_drafts(scripts, target_count=1)

        self.assertEqual(summary["comment_count"], 3)
        self.assertEqual(summary["public_comment_count"], 1)
        self.assertEqual(summary["simulation_only_comment_count"], 2)

    def test_source_snapshot_health_detects_usable_snapshot(self):
        intel_result = {
            "pages": 1,
            "raw_posts": [
                {
                    "title": "우주 사진",
                    "content": "목성 사진이 올라옴",
                    "comments": [{"content": "ㄷㄷ"}],
                }
            ],
            "stats": {"titles": 1, "keywords": 3},
        }

        health = observability.source_snapshot_health(
            intel_result,
            requested_pages=1,
        )

        self.assertIn(health["status"], {"good", "warn"})
        self.assertEqual(health["raw_count"], 1)
        self.assertEqual(health["body_count"], 1)
        self.assertEqual(health["comment_count"], 1)

    def test_source_snapshot_uses_stat_comment_count_when_raw_comments_sparse(self):
        intel_result = {
            "pages": 1,
            "raw_posts": [
                {"title": f"외행성 사진 {idx}", "content": ""}
                for idx in range(24)
            ],
            "stats": {"comments": 15},
        }

        health = observability.source_snapshot_health(intel_result)

        self.assertEqual(health["comment_count"], 15)
        self.assertEqual(health["status"], "warn")
        self.assertIn("bodies", health["note"])

    def test_records_run_timeline_and_cycle(self):
        state = {}
        observability.start_run(
            state,
            mode="rehearsal",
            gallery_id="universe",
            target_count=10,
            reset=True,
        )
        record = observability.record_cycle(
            state,
            cycle=1,
            mode="rehearsal",
            scripts=[{"title": "태양 흑점", "content": "요즘 활동 많음?"}],
            target_count=10,
            gallery_id="universe",
        )

        self.assertEqual(state["run_mode"], "rehearsal")
        self.assertEqual(record["summary"]["valid"], 1)
        self.assertGreaterEqual(len(state["run_timeline"]), 2)

    def test_ops_markdown_can_include_stability_section(self):
        state = {}
        observability.start_run(
            state,
            mode="infinite",
            gallery_id="universe",
            target_count=10,
            reset=True,
        )

        text = observability.format_ops_markdown(
            state=state,
            scripts=[],
            logs=[],
            intel_result={},
            stability_markdown="## Stability\n- Status: `good`",
        )

        self.assertIn("# Ghost Protocol 운영 리포트", text)
        self.assertIn("## Stability", text)

    def test_ops_markdown_reports_comment_candidate_split(self):
        state = {}
        observability.start_run(
            state,
            mode="infinite",
            gallery_id="universe",
            target_count=1,
            reset=True,
        )

        text = observability.format_ops_markdown(
            state=state,
            scripts=[
                {
                    "title": "T",
                    "content": "C",
                    "target_comments": [
                        {"post_no": "1", "comment": "public"},
                        {"post_no": "2", "comment": "rehearsal", "simulation_only": True},
                    ],
                }
            ],
            logs=[],
            intel_result={},
        )

        self.assertIn("- Comment candidates: 1 public · 1 rehearsal-only", text)


if __name__ == "__main__":
    unittest.main()
