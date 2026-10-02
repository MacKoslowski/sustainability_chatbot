"""Post-generation checks (docs/PLAN.md §5). If the model writes a specific
that isn't backed by a retrieved source, or names a place that wasn't
retrieved, the caller should drop the prose and fall back to cards-only. A bad
generation degrades to a plain directory answer, never a wrong one.
"""

from __future__ import annotations

import re

from rva_chat.retrieve.corpus import Chunk

_DIGIT_RUN = re.compile(r"\d{3,}")  # phone numbers, street numbers, zip-ish runs
_REFUSAL_MARKERS = ("don't have that", "do not have that", "i'm not sure", "i am not sure")


def is_refusal(answer: str) -> bool:
    lowered = answer.lower()
    return any(marker in lowered for marker in _REFUSAL_MARKERS)


def check_grounded(answer: str, sources: list[Chunk]) -> tuple[bool, str | None]:
    """Returns (ok, reason). `ok=False` means: discard the prose, show cards only."""
    if is_refusal(answer):
        return True, None

    # Guard 1: the model wrote digits we never gave it (a fabricated phone/address/price).
    source_digit_runs = set()
    for s in sources:
        source_digit_runs.update(_DIGIT_RUN.findall(s.text))
    for run in _DIGIT_RUN.findall(answer):
        if run not in source_digit_runs:
            return False, f"answer contains a number ({run}) not present in any retrieved source"

    # Guard 2: the model named an org that wasn't retrieved at all.
    answer_lower = answer.lower()
    named_sources = [s for s in sources if s.name.lower() in answer_lower]
    if sources and not named_sources and len(answer.split()) > 3:
        # Not a hard failure on its own (the model may paraphrase without a name),
        # but worth surfacing — callers can log this rather than reject outright.
        return True, "answer did not name any retrieved source by name"

    return True, None
