"""Pure helpers for filling infinite-mode batches before publishing."""

from __future__ import annotations


def valid_scripts(scripts: list[dict] | tuple) -> list[dict]:
    return [
        dict(script)
        for script in (scripts or [])
        if isinstance(script, dict)
        and not script.get("_failed")
        and str(script.get("title") or "").strip()
        and str(script.get("content") or "").strip()
    ]


def merge_valid_scripts(
    accumulated: list[dict] | tuple,
    incoming: list[dict] | tuple,
    *,
    target_count: int,
) -> list[dict]:
    """Merge valid drafts while removing exact title/body duplicates."""

    target = max(1, int(target_count or 1))
    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for script in [*valid_scripts(accumulated), *valid_scripts(incoming)]:
        key = (
            " ".join(str(script.get("title") or "").lower().split()),
            " ".join(str(script.get("content") or "").lower().split()),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(script)
        if len(merged) >= target:
            break
    return merged


def missing_count(scripts: list[dict] | tuple, target_count: int) -> int:
    return max(0, max(1, int(target_count or 1)) - len(valid_scripts(scripts)))


def renumber_scripts(scripts: list[dict] | tuple) -> list[dict]:
    return [
        {**script, "wave": index}
        for index, script in enumerate(valid_scripts(scripts), 1)
    ]
