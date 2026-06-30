import tempfile
import unittest
from pathlib import Path

from ghost_protocol.ui.gallery_history import load_history, save_history


class GalleryHistoryTest(unittest.TestCase):
    def test_missing_history_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_history(Path(tmp) / "missing.json"), [])

    def test_save_history_dedupes_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            save_history("alpha", "mgallery", path=path)
            save_history("beta", "board", path=path)
            save_history("alpha", "mini", path=path)
            history = load_history(path)
            self.assertEqual([item["gallery_id"] for item in history], ["alpha", "beta"])
            self.assertEqual(history[0]["type_label"], "mini")


if __name__ == "__main__":
    unittest.main()
