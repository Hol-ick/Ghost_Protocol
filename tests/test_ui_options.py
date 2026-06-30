import unittest

from ghost_protocol.ui.options import (
    DEFAULT_GALLERY_TYPE_LABEL,
    DEFAULT_LENGTH_LABEL,
    DEFAULT_TONE_LABEL,
    LENGTH_OPTIONS,
    TYPE_MAP,
    TONE_MAP,
    gallery_type_for_label,
    tone_for_label,
)


class UiOptionsTest(unittest.TestCase):
    def test_defaults_resolve_to_expected_values(self):
        self.assertEqual(gallery_type_for_label(DEFAULT_GALLERY_TYPE_LABEL), "mgallery")
        self.assertEqual(tone_for_label(DEFAULT_TONE_LABEL), "cynical")
        self.assertIn(DEFAULT_LENGTH_LABEL, LENGTH_OPTIONS)

    def test_unknown_labels_fall_back_to_defaults(self):
        self.assertEqual(gallery_type_for_label("unknown"), TYPE_MAP[DEFAULT_GALLERY_TYPE_LABEL])
        self.assertEqual(tone_for_label("unknown"), TONE_MAP[DEFAULT_TONE_LABEL])


if __name__ == "__main__":
    unittest.main()
