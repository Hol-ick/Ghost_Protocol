"""Small validation policies used by generation workflows."""

from __future__ import annotations

import re


def validate_slot_diversity(summary: str) -> str | None:
    """Return overlap details when [A:], [B:], [C:] slots reuse core terms."""
    slots: dict[str, str] = {}
    for match in re.finditer(r"\[([ABC]):\s*([^\]]+)\]", summary):
        slots[match.group(1)] = match.group(2).strip()
    if len(slots) < 2:
        return None

    slot_nouns: dict[str, set[str]] = {}
    for label, text in slots.items():
        words = {
            word.strip("?!.,~ㅋㅠㅡ()[]{}\"'")
            for word in text.split()
            if len(word.strip("?!.,~ㅋㅠㅡ()[]{}\"'")) >= 2
        }
        slot_nouns[label] = words

    labels = list(slot_nouns.keys())
    overlaps: list[str] = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            shared = slot_nouns[labels[i]] & slot_nouns[labels[j]]
            if shared:
                overlaps.append(f"[{labels[i]}]∩[{labels[j]}]={shared}")
    return " | ".join(overlaps) if overlaps else None
