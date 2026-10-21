"""
Turn a list of kept segments into an actual ffmpeg invocation.

This module builds *plans* — strings and argument lists — and does not run
ffmpeg. Keeping it pure is deliberate: the timeline maths is where the bugs
live, and it is fully testable without a media file or ffmpeg on PATH.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .edits import Segment


class FFmpegPlanError(ValueError):
    """Raised when a plan cannot be built."""


def _concat_escape(path: str) -> str:
    """
    Escape a path for ffmpeg's concat demuxer.

    The demuxer treats single quotes as string delimiters, so a path containing
    an apostrophe (very common: "Chirag's demo.mp4") breaks the file list unless
    the quote is closed, escaped, and reopened.
    """
    return path.replace("'", "'\\''")


@dataclass(frozen=True)
class ConcatEntry:
    source: str
    inpoint: float
    outpoint: float

    def to_concat_lines(self) -> list[str]:
        return [
            f"file '{_concat_escape(self.source)}'",
            f"inpoint {self.inpoint:.3f}",
            f"outpoint {self.outpoint:.3f}",
        ]


@dataclass(frozen=True)
class FFmpegPlan:
    """A complete, ready-to-run ffmpeg invocation."""

    args: list[str]
    concat_file_body: str
    segments: tuple[Segment, ...]

    @property
    def command(self) -> str:
        return " ".join(shlex.quote(a) for a in self.args)

    @property
    def total_duration(self) -> float:
        return round(sum(s.duration for s in self.segments), 3)


def build_concat_file(
    segments: Sequence[Segment],
    source: str | Path,
) -> str:
    """
    Render the concat-demuxer file body for a list of segments.

    Every entry points at the SAME source with a different in/out point, which
    avoids writing N intermediate clips to disk.
    """
    if not segments:
        raise FFmpegPlanError(
            "no segments to export — every word was deleted, or the transcript is empty"
        )

    source_str = str(source)
    lines = ["ffconcat version 1.0"]
    for segment in segments:
        lines.extend(ConcatEntry(source_str, segment.start, segment.end).to_concat_lines())
    return "\n".join(lines) + "\n"


def build_plan(
    segments: Sequence[Segment],
    source: str | Path,
    output: str | Path,
    *,
    concat_file: str | Path = "bolcut_concat.txt",
    crf: int = 20,
    preset: str = "medium",
    audio_only: bool = False,
    copy_codecs: bool = False,
) -> FFmpegPlan:
    """
    Build the ffmpeg command that produces the edited file.

    `copy_codecs=True` avoids re-encoding but can only cut on keyframes, so the
    result may be up to a few seconds off. Off by default: transcript editing
    cuts mid-word, and keyframe-snapping would be visibly wrong.
    """
    if copy_codecs and not audio_only:
        # Stream copy cannot honour arbitrary inpoints. Warn by refusing rather
        # than silently shipping a mis-cut video.
        raise FFmpegPlanError(
            "copy_codecs (stream copy) can only cut on keyframes, so it cannot "
            "honour mid-word cut points in video. Use copy_codecs only with "
            "audio_only=True, or drop it and let bolcut re-encode."
        )

    body = build_concat_file(segments, source)

    args = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
    ]

    if audio_only:
        if copy_codecs:
            args += ["-c", "copy"]
        else:
            args += ["-vn", "-c:a", "aac", "-b:a", "192k"]
    else:
        args += [
            "-c:v", "libx264",
            "-crf", str(crf),
            "-preset", preset,
            "-c:a", "aac",
            "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
        ]

    args.append(str(output))

    return FFmpegPlan(
        args=args,
        concat_file_body=body,
        segments=tuple(segments),
    )


def build_trim_filters(segments: Sequence[Segment]) -> str:
    """
    Alternative to the concat demuxer: a filter_complex trim/select chain.

    More precise than the demuxer on some containers, and the only option when
    the source is a stream. Returns the `-filter_complex` argument value.
    """
    if not segments:
        raise FFmpegPlanError("no segments to export")

    video_parts = []
    audio_parts = []
    concat_inputs = []

    for i, segment in enumerate(segments):
        video_parts.append(
            f"[0:v]trim=start={segment.start:.3f}:end={segment.end:.3f},"
            f"setpts=PTS-STARTPTS[v{i}]"
        )
        audio_parts.append(
            f"[0:a]atrim=start={segment.start:.3f}:end={segment.end:.3f},"
            f"asetpts=PTS-STARTPTS[a{i}]"
        )
        concat_inputs.append(f"[v{i}][a{i}]")

    n = len(segments)
    concat = f"{''.join(concat_inputs)}concat=n={n}:v=1:a=1[outv][outa]"
    return ";".join(video_parts + audio_parts + [concat])
