"""
Filler-word detection — the feature that makes this feel like magic.

Two modes:
  * a built-in list (English + Hinglish), for zero-setup use
  * `most_repeated()`, which finds a user's own verbal tics from the transcript
    itself. This is the one that matters for Indian creators, whose fillers are
    often code-mixed and would never appear on an English list.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from .transcript import Transcript

# Deliberately short. A long list produces false positives on real content —
# "like" and "so" are fillers sometimes and actual words most of the time.
ENGLISH_FILLERS = frozenset({
    "um", "uh", "er", "ah", "mm", "hmm", "uhh", "umm",
})

HINGLISH_FILLERS = frozenset({
    "arre", "matlab", "yani", "acha", "accha", "theek", "hai",
    "waghera", "sab", "bol",
})

DEFAULT_FILLERS = ENGLISH_FILLERS | frozenset({"arre", "matlab", "yani"})


def _clean(word: str) -> str:
    return word.strip().strip(".,!?;:\"'()[]{}").lower()


def find_fillers(
    transcript: Transcript,
    words: Iterable[str] = DEFAULT_FILLERS,
) -> list[int]:
    """Indices of words matching the filler list."""
    targets = {w.lower() for w in words}
    return [i for i, w in enumerate(transcript.words) if _clean(w.text) in targets]


def most_repeated(transcript: Transcript, *, limit: int = 5, min_length: int = 2) -> list[tuple[str, int]]:
    """
    The user's own most-used short words, with counts.

    This is how you catch a personal tic that no list would contain — someone
    who says "basically" 40 times, or "dekho" 30 times.
    """
    counts = Counter(
        _clean(w.text) for w in transcript.words if len(_clean(w.text)) >= min_length
    )
    return counts.most_common(limit)
