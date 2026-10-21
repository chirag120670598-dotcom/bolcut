"""Rebuild an SRT subtitle track for the *edited* file."""
from __future__ import annotations

from typing import Iterable

from .transcript import Word


def format_timestamp(seconds: float) -> str:
    """SRT wants HH:MM:SS,mmm — a comma, not a dot."""
    if seconds < 0:
        seconds = 0.0
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_timestamp(value: str) -> float:
    """Accept SRT (comma) or plain HH:MM:SS.mmm (dot)."""
    text = value.strip().replace(",", ".")
    parts = text.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(parts[0])
    except ValueError as exc:
        raise ValueError(f"cannot parse timestamp {value!r}") from exc


def build_srt(words: Iterable[Word], *, lines_per_cue: int = 8) -> str:
    """
    Group words into readable cues and render SRT.

    One word per cue is unreadable; 8 words is roughly a sentence and matches
    what editors expect.
    """
    words = list(words)
    if not words:
        return ""

    cues = [words[i : i + lines_per_cue] for i in range(0, len(words), lines_per_cue)]
    blocks = []
    for number, cue in enumerate(cues, start=1):
        text = " ".join(w.text.strip() for w in cue if w.text.strip())
        blocks.append(
            f"{number}\n"
            f"{format_timestamp(cue[0].start)} --> {format_timestamp(cue[-1].end)}\n"
            f"{text}\n"
        )
    return "\n".join(blocks) + "\n"
