"""Runtime log file helpers for application workflows."""

from __future__ import annotations

from pathlib import Path


def append_text_log(text: str, log_path: str | Path) -> None:
    """Append text to a log file, creating its parent directory when needed.

    This helper intentionally swallows write failures because these logs are
    operational conveniences and should not break a running batch.
    """
    try:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except Exception:
        pass
