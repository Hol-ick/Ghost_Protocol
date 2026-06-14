"""Recent gallery history persistence."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
HISTORY_PATH = PROJECT_ROOT / "gallery_history.json"
HISTORY_MAX = 8


def load_history(path: Path = HISTORY_PATH) -> list[dict]:
    """Load recent gallery selections. Bad or missing files become empty history."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_history(
    gallery_id: str,
    type_label: str,
    *,
    path: Path = HISTORY_PATH,
    max_items: int = HISTORY_MAX,
) -> None:
    """Save a gallery selection newest-first with duplicates removed."""
    if not gallery_id.strip():
        return
    data = [entry for entry in load_history(path) if entry.get("gallery_id") != gallery_id]
    data.insert(0, {"gallery_id": gallery_id, "type_label": type_label})
    try:
        path.write_text(
            json.dumps(data[:max_items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
