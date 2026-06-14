import tempfile
import unittest
from pathlib import Path

from ghost_protocol.ui import intel_cache


class IntelCacheTest(unittest.TestCase):
    def test_cache_key_resolves_gallery_type_label(self):
        self.assertEqual(intel_cache.cache_key("abc", "정규 (board)"), "abc::board")

    def test_cache_freshness_uses_ttl(self):
        entry = {"ts": 100.0}
        self.assertTrue(intel_cache.is_cache_fresh(entry, now=150.0, ttl=60))
        self.assertFalse(intel_cache.is_cache_fresh(entry, now=161.0, ttl=60))

    def test_last_topic_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "last_topic_cache.json"
            intel_cache.save_last_topic_cache(
                result={"x": 1},
                gallery_id="abc",
                type_label="마이너 (mgallery)",
                path=path,
                ts=123.0,
            )
            loaded = intel_cache.load_last_topic_cache(path)
            self.assertEqual(loaded["result"], {"x": 1})
            self.assertEqual(loaded["gallery_id"], "abc")
            self.assertEqual(loaded["ts"], 123.0)


if __name__ == "__main__":
    unittest.main()
