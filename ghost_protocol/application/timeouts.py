"""Small timeout helpers for blocking SDK calls."""

from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from typing import Any


def run_with_timeout(
    fn: Callable[..., Any],
    *args: Any,
    timeout: float,
    **kwargs: Any,
) -> Any:
    """Run a blocking callable without waiting for it again after timeout.

    ``ThreadPoolExecutor`` used as a context manager calls ``shutdown(wait=True)``
    on exit. That makes ``future.result(timeout=...)`` appear to time out while
    the caller still blocks until the underlying SDK call returns. Explicit
    non-waiting shutdown preserves the timeout boundary.
    """

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
