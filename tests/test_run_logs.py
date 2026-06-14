import tempfile
import unittest
from pathlib import Path

from ghost_protocol.application.run_logs import append_text_log


class RunLogsTest(unittest.TestCase):
    def test_append_text_log_creates_parent_and_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "run.txt"
            append_text_log("first", path)
            append_text_log("second", path)
            self.assertEqual(path.read_text(encoding="utf-8"), "first\nsecond\n")


if __name__ == "__main__":
    unittest.main()
