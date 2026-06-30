import unittest

from ghost_protocol.domain.validators import validate_slot_diversity


class SlotDiversityTest(unittest.TestCase):
    def test_returns_none_for_distinct_slots(self):
        summary = "[A: alpha beta] [B: gamma delta]"
        self.assertIsNone(validate_slot_diversity(summary))

    def test_reports_overlap(self):
        summary = "[A: alpha beta] [B: beta gamma]"
        result = validate_slot_diversity(summary)
        self.assertIsNotNone(result)
        self.assertIn("[A]∩[B]", result)


if __name__ == "__main__":
    unittest.main()
