import unittest
from unittest.mock import patch

from ghost_protocol.application import data_exports


class DataExportsTest(unittest.TestCase):
    def test_export_limit_is_positive(self):
        self.assertGreater(data_exports.EXPORT_HARD_LIMIT, 0)

    def test_export_counts_delegate_to_database(self):
        with patch.object(data_exports, "database") as db:
            db.get_post_count.return_value = 7
            db.get_comment_count.return_value = 11

            self.assertEqual(data_exports.get_export_counts("gallery"), (7, 11))

            db.get_post_count.assert_called_once_with("gallery")
            db.get_comment_count.assert_called_once_with("gallery")

    def test_csv_builders_delegate_to_database(self):
        with patch.object(data_exports, "database") as db:
            db.build_posts_csv_bytes.return_value = (b"posts", 2)
            db.build_comments_csv_bytes.return_value = (b"comments", 3)

            self.assertEqual(data_exports.build_posts_csv("gallery"), (b"posts", 2))
            self.assertEqual(data_exports.build_comments_csv("gallery"), (b"comments", 3))


if __name__ == "__main__":
    unittest.main()
