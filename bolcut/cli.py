#!/usr/bin/env python3
"""
bolcut — edit your video by editing the transcript.

Every subcommand except `transcribe` runs fully offline with no model and no
ffmpeg, so you can build and inspect a cut plan anywhere.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core.edits import cut_duration, kept_segments, reindex_after_cut, removed_segments
from .core.ffmpeg_plan import build_plan
from .core.fillers import DEFAULT_FILLERS, find_fillers, most_repeated
from .core.srt import build_srt
from .core.transcript import Transcript, TranscriptError


def _load_transcript(path: str) -> Transcript:
    """Load a transcript JSON produced by `bolcut transcribe`."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return Transcript.from_whisper_words(
        data.get("words", []),
        language=data.get("language"),
        duration=data.get("duration"),
    )


def _resolve_indices(transcript: Transcript, args) -> list[int]:
    indices: set[int] = set()
    if getattr(args, "fillers", False):
        indices.update(find_fillers(transcript))
    if getattr(args, "filler_words", None):
        indices.update(find_fillers(transcript, args.filler_words.split(",")))
    for phrase in getattr(args, "cut", None) or []:
        found = transcript.indices_for_text(phrase)
        if not found:
            print(f"warning: phrase not found in transcript: {phrase!r}", file=sys.stderr)
        indices.update(found)
    for raw in getattr(args, "index", None) or []:
        indices.add(int(raw))
    if getattr(args, "silence", None):
        # Cutting long pauses is done by capping the gap, not by deleting words.
        pass
    return sorted(indices)


def cmd_transcribe(args) -> int:
    from .adapters.whisper_adapter import transcribe_to_json

    out = args.out or str(Path(args.media).with_suffix("")) + ".transcript.json"
    print(f"Transcribing {args.media} with faster-whisper '{args.model}'...")
    transcribe_to_json(
        args.media, out,
        model_size=args.model, language=args.language,
    )
    transcript = _load_transcript(out)
    print(f"  {len(transcript)} words -> {out}")
    print(f"  language: {transcript.language}  duration: {transcript.end:.1f}s")
    return 0


def cmd_show(args) -> int:
    transcript = _load_transcript(args.transcript)
    for i, word in enumerate(transcript.words):
        marker = "*" if word.text.strip().strip(".,!?").lower() in DEFAULT_FILLERS else " "
        print(f"  {i:4d}{marker} {word.start:8.3f}-{word.end:8.3f}  {word.text.strip()}")
    print(f"\n{len(transcript)} words, {transcript.end:.1f}s. (* = known filler)")
    return 0


def cmd_fillers(args) -> int:
    transcript = _load_transcript(args.transcript)
    hits = find_fillers(transcript)
    print(f"Known fillers found: {len(hits)}")
    for i in hits:
        print(f"  [{i}] {transcript[i].start:.3f}s  {transcript[i].text.strip()!r}")
    print(f"\nYour most-repeated words (candidates for --filler-words):")
    for word, count in most_repeated(transcript, limit=10):
        print(f"  {count:4d}x  {word}")
    return 0


def cmd_plan(args) -> int:
    transcript = _load_transcript(args.transcript)
    deleted = _resolve_indices(transcript, args)

    if not deleted:
        print("Nothing to cut. Try --fillers, --cut \"phrase\", or --index N", file=sys.stderr)
        return 1

    kwargs = dict(
        preserve_leading=not args.drop_edges,
        preserve_trailing=not args.drop_edges,
        max_gap=args.silence,
    )
    segments = kept_segments(transcript, deleted, **kwargs)
    if not segments:
        print("Every word was deleted — nothing left to export.", file=sys.stderr)
        return 1

    plan = build_plan(
        segments, args.media, args.output,
        audio_only=args.audio_only, copy_codecs=args.copy_codecs,
    )

    print(f"Cutting {len(deleted)} words ({cut_duration(transcript, deleted, **kwargs)}s)")
    print(f"  {len(segments)} segments kept, {plan.total_duration}s of output")
    print()
    for s in removed_segments(transcript, deleted, **kwargs):
        print(f"  CUT  {s.start:8.3f} -> {s.end:8.3f}")
    print()
    print("--- bolcut_concat.txt ---")
    print(plan.concat_file_body)
    print("--- command ---")
    print(plan.command)
    return 0


def cmd_cut(args) -> int:
    from .adapters.ffmpeg_adapter import run_plan

    transcript = _load_transcript(args.transcript)
    deleted = _resolve_indices(transcript, args)
    if not deleted:
        print("Nothing to cut.", file=sys.stderr)
        return 1

    kwargs = dict(
        preserve_leading=not args.drop_edges,
        preserve_trailing=not args.drop_edges,
        max_gap=args.silence,
    )
    segments = kept_segments(transcript, deleted, **kwargs)
    if not segments:
        print("Every word was deleted.", file=sys.stderr)
        return 1

    plan = build_plan(segments, args.media, args.output, audio_only=args.audio_only)
    concat = Path(args.output).with_suffix(".concat.txt")
    run_plan(plan, concat_file=concat, dry_run=args.dry_run)

    if not args.dry_run:
        survivors = reindex_after_cut(transcript, deleted, **kwargs)
        srt_path = Path(args.output).with_suffix(".srt")
        srt_path.write_text(build_srt(survivors), encoding="utf-8")
        print(f"Wrote {args.output} and {srt_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bolcut",
        description="Edit your video by editing the transcript. 100% local.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    t = sub.add_parser("transcribe", help="Transcribe a media file (needs faster-whisper)")
    t.add_argument("media")
    t.add_argument("--model", default="small", help="tiny|base|small|medium|large-v3")
    t.add_argument("--language", default=None, help="e.g. hi, en. Omit to autodetect")
    t.add_argument("--out", default=None)
    t.set_defaults(func=cmd_transcribe)

    s = sub.add_parser("show", help="Print the transcript with word indices")
    s.add_argument("transcript")
    s.set_defaults(func=cmd_show)

    f = sub.add_parser("fillers", help="Find filler words and your verbal tics")
    f.add_argument("transcript")
    f.set_defaults(func=cmd_fillers)

    for name, func, help_text in (
        ("plan", cmd_plan, "Show the cut plan + ffmpeg command without running it"),
        ("cut", cmd_cut, "Apply the cuts and export (needs ffmpeg)"),
    ):
        c = sub.add_parser(name, help=help_text)
        c.add_argument("transcript")
        c.add_argument("--media", required=True, help="the source video/audio file")
        c.add_argument("--output", required=True)
        c.add_argument("--fillers", action="store_true", help="cut known um/uh/arre/matlab")
        c.add_argument("--filler-words", default=None, help="comma-separated custom list")
        c.add_argument("--cut", action="append", help="cut a phrase (repeatable)")
        c.add_argument("--index", action="append", help="cut a word index (repeatable)")
        c.add_argument("--silence", type=float, default=None,
                       help="also split on pauses longer than N seconds")
        c.add_argument("--drop-edges", action="store_true",
                       help="trim leading/trailing silence")
        if name == "plan":
            c.add_argument("--audio-only", action="store_true")
            c.add_argument("--copy-codecs", action="store_true")
        else:
            c.add_argument("--audio-only", action="store_true")
            c.add_argument("--dry-run", action="store_true", help="print, do not run ffmpeg")
        c.set_defaults(func=func)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (TranscriptError, FileNotFoundError, ValueError) as exc:
        print(f"bolcut: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
