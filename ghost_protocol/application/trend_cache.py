"""Small disk cache for local-LLM trend-analysis JSON payloads."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ghost_protocol.application import llm_usage


_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "ollama_trend_cache.json"
_MAX_ENTRIES = 80


def _read_cache(path: Path | None = None) -> dict[str, Any]:
    path = path or _CACHE_PATH
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_cache(data: dict[str, Any], path: Path | None = None) -> None:
    path = path or _CACHE_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        # Cache writes should never break the primary workflow.
        return


def build_key(
    *,
    gallery_id: str,
    titles: list[str],
    comments: list[str],
    prompt_template: str,
    extra: str = "",
) -> str:
    payload = {
        "gallery_id": gallery_id,
        "titles": titles[:80],
        "comments": comments[:50],
        "prompt_hash": hashlib.sha256(prompt_template.encode("utf-8")).hexdigest()[:16],
        "extra": extra,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get(key: str, *, ttl_seconds: int | None = None) -> dict[str, Any] | None:
    ttl = llm_usage.trend_cache_ttl_seconds() if ttl_seconds is None else int(ttl_seconds)
    if ttl <= 0 or not key:
        return None
    data = _read_cache()
    entry = data.get(key)
    if not isinstance(entry, dict):
        return None
    ts = float(entry.get("ts") or 0)
    if time.time() - ts > ttl:
        return None
    result = entry.get("result")
    if not isinstance(result, dict):
        return None
    return dict(result)


def set(key: str, result: dict[str, Any]) -> None:
    if llm_usage.trend_cache_ttl_seconds() <= 0 or not key or not isinstance(result, dict):
        return
    data = _read_cache()
    data[key] = {
        "ts": time.time(),
        "result": dict(result),
    }
    if len(data) > _MAX_ENTRIES:
        ordered = sorted(
            data.items(),
            key=lambda item: float((item[1] or {}).get("ts") or 0),
            reverse=True,
        )
        data = dict(ordered[:_MAX_ENTRIES])
    _write_cache(data)
