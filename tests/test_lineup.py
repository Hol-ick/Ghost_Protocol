import unittest
from collections import Counter
from unittest.mock import patch

from ghost_protocol.domain import lineup


class LineupPolicyTest(unittest.TestCase):
    def test_zero_wave_returns_empty_lineup(self):
        self.assertEqual(lineup.build_balanced_lineup(0), [])

    def test_lineup_has_requested_length(self):
        with patch("random.shuffle", lambda items: None):
            result = lineup.build_balanced_lineup(8, sentiment_score=0, hour=12)
        self.assertEqual(len(result), 8)
        keys = {item["key"] for item in result}
        self.assertIn("scene_noticer", keys)
        self.assertIn("detail_extender", keys)
        self.assertIn("light_joker", keys)
        self.assertIn("experience_linker", keys)
        self.assertIn("possibility_mapper", keys)
        self.assertEqual(len(keys), 8)

    def test_fix_consecutive_same_reduces_adjacent_duplicates(self):
        items = [
            {"key": "a"},
            {"key": "a"},
            {"key": "b"},
            {"key": "c"},
        ]
        result = lineup.fix_consecutive_same(items)
        self.assertNotEqual(result[0]["key"], result[1]["key"])

    def test_fix_consecutive_hot_breaks_three_hot_run_when_possible(self):
        items = [
            {"key": "aggressive"},
            {"key": "aggro"},
            {"key": "doomer"},
            {"key": "neutral"},
        ]
        result = lineup.fix_consecutive_hot(items)
        first_three = [item["key"] for item in result[:3]]
        self.assertFalse(all(key in lineup.PERSONA_HOT_KEYS for key in first_three))

    def test_lineup_keeps_attention_heavy_personas_low(self):
        with (
            patch("random.shuffle", lambda items: None),
            patch("random.randint", lambda _start, end: end),
        ):
            result = lineup.build_balanced_lineup(20, sentiment_score=0, hour=12)

        attention_heavy = [
            item for item in result if item["key"] in lineup.ATTENTION_HEAVY_KEYS
        ]
        self.assertLessEqual(len(attention_heavy), 3)
        self.assertNotIn("rally_crier", {item["key"] for item in result})

    def test_active_personas_do_not_require_question_scaffolds(self):
        self.assertFalse(lineup.QUESTION_HEAVY_KEYS)
        self.assertTrue(
            all(
                item["key"] not in lineup.QUESTION_HEAVY_KEYS
                for item in lineup.ACTIVE_PERSONA_POOL
            )
        )

    def test_new_lineups_exclude_context_seeking_legacy_roles(self):
        result = lineup.build_balanced_lineup(20, sentiment_score=0, hour=12)
        keys = {item["key"] for item in result}

        self.assertFalse(
            keys
            & {
                "lazy_questioner",
                "self_deprecator",
                "meta_observer",
                "score_reporter",
                "rally_crier",
                "paranoid",
                "cynical",
                "aggressive",
                "aggro",
                "doomer",
                "conviction_defender",
                "ventilator",
                "monologue",
                "humblebragger",
            }
        )

    def test_default_lineup_does_not_require_complaint_personas(self):
        excluded = {
            "cynical",
            "aggressive",
            "aggro",
            "doomer",
            "conviction_defender",
            "ventilator",
        }
        for _ in range(30):
            result = lineup.build_balanced_lineup(20, sentiment_score=0, hour=12)
            self.assertFalse({item["key"] for item in result} & excluded)

    def test_large_lineup_caps_each_persona_at_two_uses(self):
        result = lineup.build_balanced_lineup(20, sentiment_score=0, hour=12)
        counts = Counter(item["key"] for item in result)

        self.assertLessEqual(max(counts.values()), 2)

    def test_small_lineup_prefers_unique_personas(self):
        duplicated = [
            lineup.PERSONA_BY_KEY["scene_noticer"],
            lineup.PERSONA_BY_KEY["scene_noticer"],
            lineup.PERSONA_BY_KEY["detail_extender"],
        ]

        result = lineup.prefer_unique_when_possible(duplicated)
        self.assertEqual(len({item["key"] for item in result}), 3)


if __name__ == "__main__":
    unittest.main()
