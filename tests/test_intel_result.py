import unittest

from ghost_protocol.application.intel_result import (
    TrendPayloadError,
    can_seed_generation,
    is_parse_failed,
    normalize_trend_payload,
    validate_trend_payload,
)


def _valid_payload(**overrides):
    payload = {
        "hot_topics": ["악력 91kg", "중고 물건 판매"],
        "sentiment": "장난",
        "memes": ["좋은 아침"],
        "summary": "[A: 악력 91kg] / [B: 중고 물건 판매] / [C: 다케시타 도리 방문]",
        "ai_analysis": "악력 수치와 중고 판매글, 일본 방문기가 섞여 가볍고 산만한 흐름이다.",
        "generation_guidance": "실제 제목에 나온 물건이나 수치를 하나만 골라 짧게 참여하고, 없는 유행을 만들지 않는다.",
    }
    payload.update(overrides)
    return payload


class IntelResultTest(unittest.TestCase):
    def test_parse_failure_cannot_seed_generation(self):
        failed = {
            "_parse_error": True,
            "ai_analysis": "파싱 실패",
            "generation_guidance": "원본 로그 확인",
            "summary": "N/A",
        }

        self.assertTrue(is_parse_failed(failed))
        self.assertFalse(can_seed_generation(failed))

    def test_completed_analysis_can_seed_generation(self):
        self.assertFalse(is_parse_failed(_valid_payload()))
        self.assertTrue(can_seed_generation(_valid_payload()))

    def test_trend_payload_accepts_exact_abc_slots(self):
        validate_trend_payload(_valid_payload())

    def test_trend_payload_rejects_extra_summary_slots(self):
        payload = _valid_payload(
            summary="[A: 악력 91kg] / [B: 중고 물건 판매] / [C: 다케시타 도리 방문] / [D: 새 패치]"
        )

        with self.assertRaises(TrendPayloadError):
            validate_trend_payload(payload)

    def test_trend_payload_rejects_unbounded_summary(self):
        payload = _valid_payload(summary="[A: 악력] / [B: 판매] / [C: 방문]" + (" 반복" * 100))

        with self.assertRaises(TrendPayloadError):
            validate_trend_payload(payload)

    def test_model_topic_slots_are_normalized_to_legacy_summary(self):
        model_payload = _valid_payload()
        model_payload.pop("summary")
        model_payload["topic_slots"] = ["악력 91kg", "중고 물건 판매", "다케시타 도리 방문"]

        result = normalize_trend_payload(model_payload)

        self.assertEqual(
            result["summary"],
            "[A: 악력 91kg] / [B: 중고 물건 판매] / [C: 다케시타 도리 방문]",
        )
        self.assertNotIn("topic_slots", result)

    def test_model_topic_slots_must_have_exactly_three_items(self):
        model_payload = _valid_payload()
        model_payload.pop("summary")
        model_payload["topic_slots"] = ["악력", "판매", "방문", "패치"]

        with self.assertRaises(TrendPayloadError):
            normalize_trend_payload(model_payload)

    def test_legacy_summary_payload_remains_readable(self):
        result = normalize_trend_payload(_valid_payload())

        self.assertEqual(result["summary"], _valid_payload()["summary"])


if __name__ == "__main__":
    unittest.main()
