"""
Word-level transcript model.

Everything downstream depends on the timestamps in here being right, so this
module is deliberately strict: it refuses overlapping or backwards words
instead of quietly producing a corrupt edit plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence


class TranscriptError(ValueError):
    """Raised when a transcript is malformed."""


@dataclass(frozen=True)
class Word:
    """One word with its position on the timeline, in seconds."""

    text: str
    start: float
    end: float

    def __post_init__(self) -> None:
        if self.start < 0:
            raise TranscriptError(f"word {self.text!r} starts before 0 ({self.start})")
        if self.end < self.start:
            raise TranscriptError(
                f"word {self.text!r} ends at {self.end} before it starts at {self.start}"
            )

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Transcript:
    """An ordered list of words covering a piece of media."""

    words: list[Word] = field(default_factory=list)
    language: str | None = None
    duration: float | None = None

    def __post_init__(self) -> None:
        self.validate()

    # ── construction ─────────────────────────────────────────────────────

    @classmethod
    def from_words(
        cls,
        words: Iterable[tuple[str, float, float]],
        language: str | None = None,
        duration: float | None = None,
    ) -> "Transcript":
        return cls(
            words=[Word(str(t), float(s), float(e)) for t, s, e in words],
            language=language,
            duration=duration,
        )

    @classmethod
    def from_whisper_words(
        cls,
        raw_words: Sequence[dict],
        language: str | None = None,
        duration: float | None = None,
    ) -> "Transcript":
        """
        Build from faster-whisper / whisper.cpp word objects.

        Accepts dicts, or anything exposing .word/.start/.end — faster-whisper
        returns `WordTiming` objects, whisper.cpp JSON gives dicts.
        """
        words: list[Word] = []
        for item in raw_words:
            if isinstance(item, dict):
                text = item.get("word") or item.get("text") or ""
                start = item.get("start")
                end = item.get("end")
            else:
                text = getattr(item, "word", "") or getattr(item, "text", "")
                start = getattr(item, "start", None)
                end = getattr(item, "end", None)

            if start is None or end is None:
                raise TranscriptError(f"word {text!r} is missing a timestamp")
            words.append(Word(str(text), float(start), float(end)))

        return cls(words=words, language=language, duration=duration)

    # ── validation ───────────────────────────────────────────────────────

    def validate(self) -> None:
        """
        Check the timeline is sane.

        Overlapping words make "delete word 5" ambiguous — two words claim the
        same span of media. Fail loudly here rather than produce a corrupt cut.
        """
        for i, word in enumerate(self.words):
            if i == 0:
                continue
            previous = self.words[i - 1]
            if word.start < previous.start:
                raise TranscriptError(
                    f"words out of order: {previous.text!r}@{previous.start} then "
                    f"{word.text!r}@{word.start}"
                )
            # A tiny overlap is normal from ASR rounding; a big one is a real bug.
            if word.start < previous.end - 0.001:
                raise TranscriptError(
                    f"words overlap: {previous.text!r} ends at {previous.end:.3f} but "
                    f"{word.text!r} starts at {word.start:.3f}"
                )

    # ── access ───────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self.words)

    def __iter__(self):
        return iter(self.words)

    def __getitem__(self, index: int) -> Word:
        return self.words[index]

    @property
    def text(self) -> str:
        """The transcript as plain text. Whisper pads with a leading space."""
        return "".join(w.text for w in self.words).strip()

    @property
    def start(self) -> float:
        return self.words[0].start if self.words else 0.0

    @property
    def end(self) -> float:
        if self.duration is not None:
            return self.duration
        return self.words[-1].end if self.words else 0.0

    def find(self, needle: str) -> list[int]:
        """
        Case-insensitive word-index matches for `needle`.

        Compares against the word stripped of punctuation, because a search for
        "um" should match the word "um,".
        """
        target = needle.strip().lower()
        hits = []
        for i, word in enumerate(self.words):
            cleaned = word.text.strip().strip(".,!?;:\"'()[]{}").lower()
            if cleaned == target:
                hits.append(i)
        return hits

    def indices_for_text(self, phrase: str) -> list[int]:
        """
        Word indices covering a whole phrase.

        Used by the CLI so `--cut "to be honest"` removes all three words.
        """
        tokens = phrase.split()
        if not tokens:
            return []
        cleaned_words = [
            w.text.strip().strip(".,!?;:\"'()[]{}").lower() for w in self.words
        ]
        for start_index in range(len(cleaned_words) - len(tokens) + 1):
            window = cleaned_words[start_index : start_index + len(tokens)]
            if window == [t.lower() for t in tokens]:
                return list(range(start_index, start_index + len(tokens)))
        return []
