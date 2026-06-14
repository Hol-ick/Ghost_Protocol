import concurrent.futures
import time
import unittest

from ghost_protocol.application.timeouts import run_with_timeout


class RunWithTimeoutTest(unittest.TestCase):
    def test_returns_completed_result(self):
        self.assertEqual(
            run_with_timeout(lambda value: value + 1, 2, timeout=0.5),
            3,
        )

    def test_timeout_does_not_wait_for_blocking_callable_to_finish(self):
        started = time.monotonic()
        with self.assertRaises(concurrent.futures.TimeoutError):
            run_with_timeout(time.sleep, 0.5, timeout=0.03)
        self.assertLess(time.monotonic() - started, 0.2)


if __name__ == "__main__":
    unittest.main()
