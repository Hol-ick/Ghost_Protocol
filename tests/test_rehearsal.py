import unittest

from ghost_protocol.application import rehearsal


class RehearsalFlowTest(unittest.TestCase):
    def test_cycle_limit_is_bounded(self):
        self.assertEqual(rehearsal.normalize_cycle_limit(None), 3)
        self.assertEqual(rehearsal.normalize_cycle_limit(0), 1)
        self.assertEqual(rehearsal.normalize_cycle_limit(99), 20)

    def test_analysis_payload_uses_only_successful_drafts(self):
        payload = rehearsal.build_analysis_payload(
            [
                {
                    "title": "첫 글",
                    "content": "첫 본문",
                    "target_comments": [{"comment": "첫 댓글"}],
                },
                {"_failed": True, "title": "실패 글", "content": "실패 본문"},
            ],
            gallery_id="universe",
        )
        self.assertEqual(payload["gallery_id"], "universe")
        self.assertEqual(payload["titles"], ["첫 글"])
        self.assertEqual(payload["comments"], ["첫 댓글"])
        self.assertEqual(payload["total_post_count"], 1)
        self.assertEqual(len(payload["raw_posts"]), 1)

    def test_analysis_payload_keeps_original_anchor_posts(self):
        payload = rehearsal.build_analysis_payload(
            [
                {
                    "title": "generated draft",
                    "content": "generated body",
                    "target_comments": [{"comment": "draft comment"}],
                },
                {"_failed": True, "title": "failed draft", "content": "failed body"},
            ],
            gallery_id="baseball_new13",
            anchor_posts=[
                {
                    "post_no": "156",
                    "title": "야라마 화질 오늘 괜찮네",
                    "content": "캡쳐가 잘 보임",
                    "comments": ["ㅋㅋㅋㅋ"],
                },
                {
                    "post_no": "157",
                    "title": "계정 판매 문의",
                    "content": "텔레그램 문의",
                    "comments": [],
                },
            ],
            anchor_topic="original briefing",
        )

        self.assertIn("generated draft", payload["titles"])
        self.assertIn("야라마 화질 오늘 괜찮네", payload["titles"])
        self.assertNotIn("계정 판매 문의", payload["titles"])
        self.assertEqual(payload["rehearsal_valid_count"], 1)
        self.assertEqual(payload["rehearsal_anchor_count"], 1)
        self.assertEqual(payload["rehearsal_anchor_topic"], "original briefing")
        self.assertIn("validation", payload["rehearsal_failure_patterns"])
        self.assertTrue(
            any(post.get("source") == "original_board_anchor" for post in payload["raw_posts"])
        )

    def test_next_topic_contains_analysis_and_guidance(self):
        topic = rehearsal.build_next_topic(
            {
                "ai_analysis": "직전 원고는 관측 장면과 장비 이야기가 중심이다.",
                "generation_guidance": "다음에는 결과와 생활 장면을 나눈다.",
                "summary": "[A: 관측] / [B: 장비] / [C: 결과]",
                "hot_topics": ["관측", "장비"],
            },
            [],
            gallery_id="universe",
        )
        self.assertIn("직전 리허설 원고와 최초 원본 게시글 앵커", topic)
        self.assertIn("다음에는 결과와 생활 장면", topic)
        self.assertIn("[씨앗 떡밥]", topic)
        self.assertIn("[리허설 기본축 앵커]", topic)
        self.assertIn("등록된 상시 분야", topic)
        self.assertIn("우주·천문", topic)
        self.assertIn("[다음 사이클 소재 배합]", topic)
        self.assertIn("새 구체 소재를 조용히 시작", topic)
        self.assertIn("[원문 표면 복제 방지]", topic)

    def test_empty_intel_uses_anchor_fallback_instead_of_empty_analysis(self):
        intel = rehearsal.normalize_cycle_intel(
            {"ai_analysis": "분석 없음", "generation_guidance": "작문 지시 없음"},
            [
                {"title": "목성 먼지대 사진 화질 좋아짐", "content": "캡처 잘 보임"},
                {
                    "_failed": True,
                    "_failure_reason": "Local LLM Rate Limit 초과 (429)",
                },
            ],
            gallery_id="universe",
            anchor_posts=[
                {
                    "title": "로또 1만개 다 꽝이면 다음 회차도 두렵지",
                    "content": "금액 남음",
                }
            ],
            anchor_topic="원본 브리핑",
        )

        self.assertNotEqual(intel["ai_analysis"], "분석 없음")
        self.assertNotEqual(intel["generation_guidance"], "작문 지시 없음")
        self.assertIn("로또 1만개", intel["ai_analysis"])
        self.assertIn("rehearsal_fallback_used", intel)

        topic = rehearsal.build_next_topic(
            intel,
            [{"title": "목성 먼지대 사진 화질 좋아짐", "content": "캡처 잘 보임"}],
            gallery_id="universe",
            anchor_posts=[
                {
                    "title": "로또 1만개 다 꽝이면 다음 회차도 두렵지",
                    "content": "금액 남음",
                }
            ],
            anchor_topic="원본 브리핑",
        )

        self.assertIn("[리허설 분석 폴백]", topic)
        self.assertNotIn("분석 없음", topic)
        self.assertIn("원본 앵커", topic)

    def test_next_topic_overrides_meaning_question_guidance(self):
        topic = rehearsal.build_next_topic(
            {
                "ai_analysis": "직전 원고는 투표 거부 밈과 환율 반응이 섞였다.",
                "generation_guidance": "'투표 거부' 밈은 뜻과 사용 맥락에 대한 질문 형태로 다룬다.",
                "summary": "[A: 투표 거부] / [B: 환율] / [C: 생활 반응]",
            },
            [],
            gallery_id="baseball_new13",
        )

        self.assertIn("[작문 지시 보정]", topic)
        self.assertIn("사용 맥락", topic)
        self.assertIn("질문은 실패율을 높이므로", topic)
        self.assertIn("평서형 반응", topic)

    def test_next_topic_extracts_repeated_terms(self):
        topic = rehearsal.build_next_topic(
            {
                "ai_analysis": "직전 원고는 선관위 사과 시점이 반복됐다.",
                "summary": "[A: 사과 시점] / [B: 관측 장면]",
            },
            [
                {"title": "선관위 사과 시점", "content": "사과 시점이 늦음"},
                {"title": "사과 시점 다시 말나옴", "content": "선관위 얘기"},
            ],
            gallery_id="universe",
        )

        self.assertIn("[직전 반복 명사]", topic)
        self.assertIn("사과", topic)
        self.assertIn("각각 0~1회", topic)

    def test_low_success_cycle_adds_recovery_rules(self):
        topic = rehearsal.build_next_topic(
            {
                "ai_analysis": "직전 원고는 목성 중력만 반복됐다.",
                "generation_guidance": "목성 중력 중심으로 쓴다.",
            },
            [
                {"title": "목성 중력으로 행성 공장 가능?", "content": "본문"},
                {"_failed": True, "title": "실패", "content": "실패"},
            ],
            gallery_id="universe",
            anchor_posts=[{"title": "코라마 화질 오늘 좋네", "content": "장면 잘 보임"}],
            anchor_topic="original source briefing",
        )

        self.assertIn("[저성공률 복구 규칙]", topic)
        self.assertIn("성공이 1/10개뿐", topic)
        self.assertIn("[R]/[G]/서브 슬롯", topic)
        self.assertIn("[원본 게시글 스냅샷 앵커]", topic)
        self.assertIn("코라마 화질 오늘 좋네", topic)
        self.assertIn("원본 게시글 스냅샷 앵커를 먼저 신뢰", topic)

    def test_next_topic_summarizes_failure_patterns_without_candidate_text(self):
        topic = rehearsal.build_next_topic(
            {
                "ai_analysis": "직전 원고는 외행성 사진과 시위 반응이 섞였다.",
            },
            [
                {"title": "외행성 사진 화질", "content": "좋아짐"},
                {
                    "_failed": True,
                    "title": "독성 후보 제목",
                    "content": "독성 후보 본문",
                    "_failure_reason": "지정 슬롯 R 대신 A을 사용했습니다.",
                },
                {
                    "_failed": True,
                    "title": "반복 후보 제목",
                    "content": "반복 후보 본문",
                    "_failure_reason": "배치 내 기존 제목과 의미적으로 동일한 글입니다.",
                },
            ],
            gallery_id="universe",
            anchor_posts=[{"title": "로또 1만개 당첨이면 금액 남음", "content": ""}],
        )

        self.assertIn("[직전 실패 패턴]", topic)
        self.assertIn("slot_drift 1회", topic)
        self.assertIn("duplicate_loop 1회", topic)
        self.assertIn("실패 후보의 문구를 살리지 말고", topic)
        self.assertNotIn("독성 후보 제목", topic)

    def test_markdown_contains_all_cycles_and_failed_candidates(self):
        text = rehearsal.format_markdown(
            [
                {
                    "cycle": 1,
                    "cycle_limit": 2,
                    "expected_count": 3,
                    "intel": {
                        "ai_analysis": "첫 분석",
                        "generation_guidance": "다음에는 장면을 나눈다.",
                    },
                    "log_lines": ["[REHEARSAL] 사이클 1/2 테스트 로그"],
                    "scripts": [
                        {"wave": 1, "title": "성공", "content": "본문"},
                        {
                            "wave": 2,
                            "_failed": True,
                            "title": "실패 후보",
                            "content": "실패 본문",
                            "_failure_reason": "검증 실패",
                        },
                    ],
                }
            ],
            gallery_id="universe",
        )
        self.assertIn("## 사이클 1 / 2", text)
        self.assertIn("### 사이클 로그", text)
        self.assertIn("[REHEARSAL] 사이클 1/2 테스트 로그", text)
        self.assertIn("### 다음 사이클 주제", text)
        self.assertIn("첫 분석", text)
        self.assertIn("### 다음 사이클 작문 지시", text)
        self.assertIn("다음에는 장면을 나눈다.", text)
        self.assertIn("### 원고 3개 목록", text)
        self.assertIn("1. [성공] 미지정 — 성공", text)
        self.assertIn("2. [실패] 미지정 — 실패 후보", text)
        self.assertIn("검증 실패", text)
        self.assertIn("3. [누락] 원고 데이터 없음", text)

    def test_markdown_strips_identity_echo_from_cycle_analysis(self):
        text = rehearsal.format_markdown(
            [
                {
                    "cycle": 1,
                    "cycle_limit": 1,
                    "expected_count": 1,
                    "intel": {
                        "ai_analysis": "ID 기반 기본축은 우주·천문입니다. 현재 수집분에서는 목성 중력 글이 이어집니다.",
                        "generation_guidance": "ID 기반 기본축은 우주·천문입니다. 현재 유행인 척하지 말고 목성 먼지 장면으로 낮춘다.",
                    },
                    "scripts": [{"wave": 1, "title": "목성 먼지", "content": "본문"}],
                }
            ],
            gallery_id="universe",
        )

        self.assertNotIn("ID 기반 기본축", text)
        self.assertIn("목성 중력 글이 이어집니다.", text)
        self.assertIn("목성 먼지 장면으로 낮춘다.", text)

    def test_rehearsal_text_strips_dangling_specific_user_placeholders(self):
        text = rehearsal.format_markdown(
            [
                {
                    "cycle": 1,
                    "cycle_limit": 1,
                    "expected_count": 1,
                    "intel": {
                        "ai_analysis": "마피아 게임 추천에 특정 유저 관심이 보이고 보드게임 카페 수익에 특정 유저 현실적인 반응이 있다.",
                        "generation_guidance": "특정 게임이나 카드에 특정 유저 직접적인 비난을 피하고, '특정 유저'과 같은 밈은 가볍게 활용하되 안전하게 쓴다.",
                    },
                    "scripts": [{"wave": 1, "title": "보드게임 카페 수익", "content": "본문"}],
                }
            ],
            gallery_id="boardgame",
        )

        self.assertNotIn("특정 유저 관심", text)
        self.assertNotIn("특정 유저 현실적인", text)
        self.assertNotIn("특정 유저 직접적인", text)
        self.assertNotIn("특정 유저'과 같은 밈", text)
        self.assertIn("마피아 게임 추천에 관심", text)
        self.assertIn("카드에 직접적인 비난", text)


if __name__ == "__main__":
    unittest.main()
