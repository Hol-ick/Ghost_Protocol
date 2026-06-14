import unittest

from ghost_protocol.domain import draft_guidance


class DraftGuidanceTest(unittest.TestCase):
    def test_extract_seed_slots(self):
        topic = "[A: 루머 확산] / [B: 도박 책임론] / [C: 타이밍 의심]"

        self.assertEqual(
            draft_guidance.extract_seed_slots(topic),
            {
                "A": "루머 확산",
                "B": "도박 책임론",
                "C": "타이밍 의심",
            },
        )

    def test_plan_wave_guidance_cycles_slots(self):
        topic = "[A: 루머 확산] / [B: 도박 책임론] / [C: 타이밍 의심]"

        slots = [
            draft_guidance.plan_wave_guidance(i, 10, topic)["slot"]
            for i in range(1, 7)
        ]

        self.assertEqual(slots, ["A", "B", "C", "A", "B", "C"])

    def test_plan_wave_guidance_keeps_late_batch_balanced(self):
        topic = "[A: 루머 확산] / [B: 도박 책임론] / [C: 타이밍 의심]"

        slots = [
            draft_guidance.plan_wave_guidance(i, 10, topic)["slot"]
            for i in range(8, 11)
        ]

        self.assertEqual(slots, ["B", "C", "A"])

    def test_plan_wave_guidance_blocks_forced_topic_switching(self):
        topic = "[A: 루머 확산] / [B: 도박 책임론] / [C: 타이밍 의심]"

        plan = draft_guidance.plan_wave_guidance(
            6,
            10,
            topic,
            persona_key="topic_diverger",
        )

        self.assertEqual(plan["angle_key"], "side_detail")
        self.assertIn("빈도 불평", plan["guidance"])
        self.assertIn("옆 소재", plan["guidance"])

    def test_persona_override_keeps_behavior_role_specific(self):
        topic = "[A: 루머 확산] / [B: 도박 책임론] / [C: 타이밍 의심]"

        plan = draft_guidance.plan_wave_guidance(
            4,
            10,
            topic,
            persona_key="paranoid",
        )

        self.assertEqual(plan["angle_key"], "low_stakes_prediction")
        self.assertIn("다음에 나올 장면", plan["guidance"])

    def test_repeated_persona_rotates_through_compatible_angles(self):
        topic = "[A: 투표 오류] / [B: 빚투] / [C: 기본소득]"

        angles = [
            draft_guidance.plan_wave_guidance(
                1,
                10,
                topic,
                persona_key="analytical",
                persona_occurrence=occurrence,
            )["angle_key"]
            for occurrence in range(3)
        ]

        self.assertEqual(
            angles,
            ["detail_extension", "scene_extension", "soft_counter"],
        )

    def test_neutral_uses_direct_reaction_not_definition_question(self):
        topic = "[A: 야대기 밈 확산] / [B: 코찰갑 논란] / [C: 책임론]"

        plan = draft_guidance.plan_wave_guidance(
            1,
            10,
            topic,
            persona_key="neutral",
        )

        self.assertEqual(plan["angle_key"], "direct_reaction")
        self.assertIn("장면 반응", plan["guidance"])

    def test_plan_wave_guidance_includes_title_structure(self):
        topic = "[A: 총선 결과 불만] / [B: 부정선거 의혹] / [C: 세대론]"

        plan = draft_guidance.plan_wave_guidance(3, 10, topic)

        self.assertIn("shape_key", plan)
        self.assertIn("제목 구조", plan["guidance"])
        self.assertIn("기본은 평서형", plan["guidance"])

    def test_universe_batch_reserves_one_gallery_purpose_wave(self):
        topic = "[A: 투표 오류] / [B: 빚투] / [C: 특정 유저 논란]"

        plans = [
            draft_guidance.plan_wave_guidance(
                i,
                5,
                topic,
                gallery_id="universe",
                source_posts=[{"title": "평면설 주장에 그럼 중력은 뭐임"}],
            )
            for i in range(1, 6)
        ]

        self.assertEqual([plan["slot"] for plan in plans].count("G"), 1)
        purpose_plan = next(plan for plan in plans if plan["slot"] == "G")
        self.assertIn("우주·천문", purpose_plan["guidance"])
        self.assertIn("평면설 주장", purpose_plan["guidance"])

    def test_large_universe_batch_reserves_balanced_gallery_purpose_waves(self):
        plans = [
            draft_guidance.plan_wave_guidance(
                i,
                20,
                "[A: 투표 오류] / [B: 빚투] / [C: 기본소득]",
                gallery_id="universe",
                source_posts=[{"title": "이번 우주 사진 해상도 미쳤네"}],
            )
            for i in range(1, 21)
        ]

        self.assertEqual([plan["slot"] for plan in plans].count("G"), 2)
        non_purpose_slots = [plan["slot"] for plan in plans if plan["slot"] != "G"]
        self.assertGreaterEqual(non_purpose_slots.count("B"), 4)
        self.assertGreaterEqual(non_purpose_slots.count("C"), 4)

    def test_purpose_waves_rotate_distinct_focuses(self):
        topic = "[A: 투표 오류] / [B: 빚투] / [C: 기본소득]"
        plans = [
            draft_guidance.plan_wave_guidance(
                i,
                10,
                topic,
                gallery_id="universe",
                source_posts=[],
            )
            for i in range(1, 11)
        ]

        purpose_focuses = [
            plan["slot_text"] for plan in plans if plan["slot"] == "G"
        ]
        self.assertEqual(len(purpose_focuses), 1)
        self.assertEqual(len(set(purpose_focuses)), 1)

    def test_gallery_purpose_requires_grounded_source_when_posts_exist(self):
        topic = "[A: live drama] / [B: camera quality] / [C: catchphrase]"
        posts = [
            {
                "title": "worldcup game time is awkward",
                "content": "not a baseball-specific post",
            }
        ]

        slots = draft_guidance.available_slots(
            topic,
            gallery_id="baseball_new13",
            source_posts=posts,
        )

        self.assertNotIn("G", slots)

    def test_real_source_slot_opens_a_topic_outside_briefing(self):
        topic = "[A: 투표 오류] / [B: 빚투] / [C: 기본소득]"
        posts = [
            {
                "post_no": "10",
                "title": "오늘 달 사진 노출 잘 잡혔네",
                "content": "구름 빠지니까 생각보다 선명함",
            }
        ]

        plans = [
            draft_guidance.plan_wave_guidance(
                i,
                8,
                topic,
                source_posts=posts,
            )
            for i in range(1, 9)
        ]

        source_plans = [plan for plan in plans if plan["slot"] == "R"]
        self.assertEqual(len(source_plans), 2)
        self.assertIn("오늘 달 사진", source_plans[0]["guidance"])
        self.assertEqual(source_plans[0]["source_post_no"], "10")

    def test_source_side_candidates_drop_unsafe_personal_posts(self):
        posts = [
            {
                "post_no": "1",
                "title": "재승이 홍어란 말을 왤케 싫어함",
                "content": "",
            },
            {
                "post_no": "2",
                "title": "편의점 삼각김밥 가격 또 올랐네",
                "content": "천원대 보기가 점점 힘듦",
            },
        ]

        candidates = draft_guidance.source_side_candidates(
            "[A: 시위 효과] / [B: 숫자 비교] / [C: 문화 논쟁]",
            posts,
            gallery_id="universe",
        )

        self.assertEqual([item["post_no"] for item in candidates], ["2"])

    def test_retry_slot_avoids_the_failed_lane(self):
        topic = "[A: 투표 오류] / [B: 빚투] / [C: 기본소득]"

        primary = draft_guidance.select_slot(1, 6, topic)
        retry = draft_guidance.select_slot(
            2,
            6,
            topic,
            excluded_slots=[primary],
        )

        self.assertEqual(primary, "A")
        self.assertNotEqual(retry, primary)

    def test_success_counts_prioritize_an_underfilled_lane(self):
        topic = "[A: 투표 오류] / [B: 빚투] / [C: 기본소득]"

        selected = draft_guidance.select_slot(
            4,
            6,
            topic,
            success_counts={"A": 2, "B": 2, "C": 0},
        )

        self.assertEqual(selected, "C")

    def test_gallery_purpose_slot_can_be_disabled_for_refill(self):
        plan = draft_guidance.plan_wave_guidance(
            1,
            1,
            "[A: 투표지 오류] / [B: 개표 기준] / [C: 선거 반응]",
            gallery_id="universe",
            purpose_slot_enabled=False,
        )

        self.assertNotEqual(plan["slot"], "G")

    def test_topic_family_matches_prefix_variants(self):
        self.assertTrue(
            draft_guidance.same_topic_family(
                "투표 오류",
                "투표지 오개입 책임",
            )
        )
        self.assertFalse(
            draft_guidance.same_topic_family(
                "투표 오류",
                "태양계 외행성 관측",
            )
        )

    def test_topic_family_cap_stays_small_for_review_batches(self):
        self.assertEqual(draft_guidance.topic_family_cap(10), 2)
        self.assertEqual(draft_guidance.topic_family_cap(20), 3)

    def test_diverse_plan_avoids_a_saturated_topic_family(self):
        topic = "[A: 투표 오류] / [B: 빚투 급증] / [C: 기본소득 재원]"
        successful = [
            draft_guidance.topic_family_tokens("투표지 오류"),
            draft_guidance.topic_family_tokens("투표 오개입"),
        ]

        plan = draft_guidance.select_diverse_plan(
            4,
            10,
            topic,
            success_counts={"A": 2, "B": 0, "C": 0},
            successful_families=successful,
        )

        self.assertNotEqual(plan["slot"], "A")


if __name__ == "__main__":
    unittest.main()
