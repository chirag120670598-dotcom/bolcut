"""
The editing engine — the actual magic trick.

Delete words in the transcript, get back the spans of media to KEEP.

This is the part that has to be exactly right. Every downstream artefact (the
ffmpeg plan, the SRT rebuild, the preview timeline) is derived from it, and a
one-frame error here shows up as a visible jump cut in the export.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .transcript import Transcript, TranscriptError, Word

# Timestamps come from ASR as floats. Comparing them for equality directly is
# how you get a phantom 0.0001s clip that ffmpeg refuses to cut. Everything
# here snaps to milliseconds before comparing.
EPSILON = 1e-3


@dataclass(frozen=True)
class Segment:
    """A span of media to keep, in seconds."""

    start: float
    end: float

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise TranscriptError(
                f"segment ends at {self.end} before it starts at {self.start}"
            )

    @property
    def duration(self) -> float:
        return self.end - self.start

    def is_empty(self) -> bool:
        return self.duration <= EPSILON


def _snap(value: float) -> float:
    """Round to whole milliseconds so float noise cannot create junk clips."""
    return round(value, 3)


def kept_segments(
    transcript: Transcript,
    deleted: Iterable[int],
    *,
    preserve_leading: bool = True,
    preserve_trailing: bool = True,
    max_gap: float | None = None,
) -> list[Segment]:
    """
    Given word indices to delete, return the spans of media to keep.

    A run of consecutive kept words becomes ONE segment spanning from the first
    word's start to the last word's end. That has two effects users expect:

    * the natural pauses *between* kept words survive, so the speech still
      sounds like speech instead of a machine gun
    * deleting a word also removes the dead air around it, which is most of why
      people use this tool

    Args:
        deleted: word indices to cut out.
        preserve_leading: keep the silence before the first kept word.
        preserve_trailing: keep the silence after the last kept word.
        max_gap: if set, split a run wherever the pause between two kept words
            exceeds this many seconds. Useful for jumping over long silences.
    """
    removed = set(deleted)
    words = transcript.words

    if not words:
        return []

    for index in removed:
        if not isinstance(index, int):
            raise TranscriptError(f"word index must be an int, got {index!r}")
        if index < 0 or index >= len(words):
            raise TranscriptError(
                f"word index {index} out of range (transcript has {len(words)} words)"
            )

    if len(removed) == len(words):
        # Everything deleted. Returning [] is correct; returning the full
        # timeline would silently export the unedited file.
        return []

    segments: list[Segment] = []
    run_start: float | None = None
    run_end: float | None = None
    previous_kept_end: float | None = None

    for index, word in enumerate(words):
        if index in removed:
            if run_start is not None and run_end is not None:
                segments.append(Segment(_snap(run_start), _snap(run_end)))
                run_start = run_end = None
            previous_kept_end = None
            continue

        if run_start is None:
            run_start = word.start
        elif (
            max_gap is not None
            and previous_kept_end is not None
            and (word.start - previous_kept_end) > max_gap + EPSILON
        ):
            segments.append(Segment(_snap(run_start), _snap(previous_kept_end)))
            run_start = word.start

        run_end = word.end
        previous_kept_end = word.end

    if run_start is not None and run_end is not None:
        segments.append(Segment(_snap(run_start), _snap(run_end)))

    if not segments:
        return []

    if preserve_leading:
        first = segments[0]
        media_start = 0.0 if transcript.words[0].start >= 0 else transcript.start
        if first.start > media_start + EPSILON:
            segments[0] = Segment(_snap(media_start), first.end)

    if preserve_trailing and transcript.duration is not None:
        last = segments[-1]
        if transcript.duration > last.end + EPSILON:
            segments[-1] = Segment(last.start, _snap(transcript.duration))

    return [s for s in segments if not s.is_empty()]


def merge_segments(segments: Sequence[Segment], tolerance: float = EPSILON) -> list[Segment]:
    """Merge segments that touch or overlap. Keeps the plan minimal."""
    ordered = sorted(segments, key=lambda s: (s.start, s.end))
    merged: list[Segment] = []
    for segment in ordered:
        if merged and segment.start <= merged[-1].end + tolerance:
            previous = merged[-1]
            merged[-1] = Segment(previous.start, max(previous.end, segment.end))
        else:
            merged.append(segment)
    return merged


def removed_segments(
    transcript: Transcript,
    deleted: Iterable[int],
    **kwargs,
) -> list[Segment]:
    """The inverse of `kept_segments` — what gets cut. Used for the preview UI."""
    kept = kept_segments(transcript, deleted, **kwargs)
    total = transcript.end
    removed: list[Segment] = []
    cursor = 0.0
    for segment in kept:
        if segment.start > cursor + EPSILON:
            removed.append(Segment(_snap(cursor), _snap(segment.start)))
        cursor = max(cursor, segment.end)
    if total > cursor + EPSILON:
        removed.append(Segment(_snap(cursor), _snap(total)))
    return removed


def deleted_word_count(transcript: Transcript, deleted: Iterable[int]) -> int:
    """How many words this edit removes. Used for the "3 words, 1.2s cut" toast."""
    return len({i for i in deleted if 0 <= i < len(transcript)})


def cut_duration(transcript: Transcript, deleted: Iterable[int], **kwargs) -> float:
    """Total seconds removed by this edit."""
    removed = removed_segments(transcript, deleted, **kwargs)
    return _snap(sum(s.duration for s in removed))


def reindex_after_cut(
    transcript: Transcript,
    deleted: Iterable[int],
    **kwargs,
) -> list[Word]:
    """
    Re-time the surviving words onto the NEW timeline.

    Needed to rebuild subtitles for the exported file: after you cut 4 seconds
    out of the middle, every later word shifts 4 seconds earlier.
    """
    removed = set(deleted)
    segments = kept_segments(transcript, deleted, **kwargs)

    # Map an original timestamp to its position in the exported file.
    def shift(original: float) -> float:
        offset = 0.0
        for segment in segments:
            if original >= segment.end:
                offset += segment.duration
            elif original > segment.start:
                offset += original - segment.start
                return _snap(offset)
        return _snap(offset)

    survivors: list[Word] = []
    for index, word in enumerate(transcript.words):
        if index in removed:
            continue
        new_start = shift(word.start)
        new_end = shift(word.end)
        if new_end <= new_start:
            new_end = new_start + EPSILON
        survivors.append(Word(word.text, new_start, new_end))
    return survivors
