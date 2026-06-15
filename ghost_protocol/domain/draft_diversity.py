"""Batch-level draft diversity helpers."""

from __future__ import annotations

import re


_SAFE_ENDING_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    ("wonder", (re.compile(r"신기(함|하네|하긴\s*함|하긴|한데|하다)?[.!?ㅋㅎ\s]*$"),)),
    ("ambiguous", (re.compile(r"애매(함|하네|하긴\s*함|하긴|한데|하다)?[.!?ㅋㅎ\s]*$"),)),
    ("curious", (re.compile(r"궁금(함|하네|하긴\s*함|하긴|한데|하다)?[.!?ㅋㅎ\s]*$"),)),
    ("nice", (re.compile(r"좋(겠다|겠네|을\s*듯|을듯)[.!?ㅋㅎ\s]*$"),)),
    ("seems", (re.compile(r"(같음|같네|같긴\s*함|같기도\s*함)[.!?ㅋㅎ\s]*$"),)),
    ("maybe", (re.compile(r"(인듯|듯|듯함|듯한데|될\s*듯|될듯)[.!?ㅋㅎ\s]*$"),)),
)


def _tail(text: object, *, size: int = 34) -> str:
    compact = re.sub(r"\s+", " ", str(text or "").strip())
    return compact[-size:]


def safe_ending_signature(title: object, content: object = "") -> str:
    """Return a coarse key for overused safe endings.

    This intentionally looks only near sentence tails. The same word may be a
    legitimate topic in the middle of a post; the problem is when every draft
    lands on the same bland aftertaste.
    """

    probes = (_tail(title), _tail(content))
    for key, patterns in _SAFE_ENDING_PATTERNS:
        if any(pattern.search(probe) for pattern in patterns for probe in probes):
            return key
    return ""


def safe_ending_cap(batch_size: int) -> int:
    """Return how many times one safe-ending family may appear in a batch."""

    if batch_size >= 20:
        return 2
    return 1
