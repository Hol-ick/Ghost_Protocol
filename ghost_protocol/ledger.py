"""Ghost Protocol — Bot Post Ledger.

Thread-safe local tracking of bot-posted post_nos per gallery.
Replaces ZWS watermark detection with deterministic ledger membership.

Storage: <project_root>/bot_ledger.json
Format:  {"gallery_id": ["post_no1", "post_no2", ...], ...}

Concurrency model:
  - Single threading.Lock for all reads and writes.
  - Atomic write: data → temp file → os.replace (avoids partial-write corruption).
  - Deduplication on write: append only if post_no not already in list.
"""

import json
import os
import threading
from pathlib import Path

# Ledger lives at project root (one level above this package directory)
_LEDGER_PATH = Path(__file__).parent.parent / "bot_ledger.json"
_LOCK = threading.Lock()


# ══════════════════════════════════════════════
# Internal helpers (caller must hold _LOCK)
# ══════════════════════════════════════════════

def _load_raw() -> dict:
    """Read ledger from disk. Returns empty dict on missing/corrupt file."""
    if not _LEDGER_PATH.exists():
        return {}
    try:
        with open(_LEDGER_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_raw(data: dict) -> None:
    """Atomically write ledger to disk. Raises OSError on failure."""
    tmp = _LEDGER_PATH.with_suffix(".tmp")
    try:
        _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _LEDGER_PATH)  # atomic on same filesystem
    except OSError:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


# ══════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════

def ledger_add(gallery_id: str, post_no: str | int) -> None:
    """Record a bot-posted post_no for gallery_id.

    Thread-safe. No-op if already recorded. Silently ignores empty values.
    """
    _no = str(post_no).strip()
    if not _no or not gallery_id:
        return
    with _LOCK:
        data = _load_raw()
        entries: list = data.setdefault(gallery_id, [])
        if _no not in entries:
            entries.append(_no)
            _save_raw(data)


def ledger_load_set(gallery_id: str) -> set:
    """Return a set of known bot post_nos for gallery_id (thread-safe).

    Loads the ledger once per call — callers should cache this when
    iterating over many posts (e.g., fetch_post_list loop).
    """
    with _LOCK:
        data = _load_raw()
    # str().strip() 강제 캐스팅: int/float 혼입 및 공백 잔여 원천 차단
    return {str(p).strip() for p in data.get(gallery_id, []) if str(p).strip()}
