"""
Tests for the bolcut editing engine.

Run with:  python -m pytest -q
"""
from __future__ import annotations

import pytest

from bolcut.core.transcript import Transcript, TranscriptError, Word
from bolcut.core import edits
from bolcut.core.edits import (
    Segment,
    cut_duration,
    kept_segments,
    merge_segments,
    reindex_after_cut,
    removed_segments,
)
from bolcut.core.ffmpeg_plan import (
    FFmpegPlanError,
    build_concat_file,
    build_plan,
    build_trim_filters,
)


def make_transcript(spec, duration=None):
    """spec is a list of (text, start, end)."""
    return Transcript.from_words(spec, language="en", duration=duration)


# A tiny "clip" used across tests: five one-second words, no gaps.
FIVE = [
    ("hello", 0.0, 1.0),
    ("my", 1.0, 2.0),
    ("name", 2.0, 3.0),
    ("is", 3.0, 4.0),
    ("chirag", 4.0, 5.0),
]


# ── Transcript ───────────────────────────────────────────────────────────────

class TestTranscript:
    def test_rejects_negative_start(self):
        with pytest.raises(TranscriptError):
            Word("x", -1.0, 0.5)

    def test_rejects_end_before_start(self):
        with pytest.raises(TranscriptError):
            Word("x", 2.0, 1.0)

    def test_rejects_out_of_order_words(self):
        with pytest.raises(TranscriptError, match="out of order"):
            Transcript.from_words([("a", 5.0, 6.0), ("b", 1.0, 2.0)])

    def test_rejects_large_overlap(self):
        with pytest.raises(TranscriptError, match="overlap"):
            Transcript.from_words([("a", 0.0, 3.0), ("b", 1.0, 4.0)])

    def test_allows_asr_rounding_overlap(self):
        # A sub-millisecond overlap is normal ASR noise, not a bug.
        t = Transcript.from_words([("a", 0.0, 1.0005), ("b", 1.0, 2.0)])
        assert len(t) == 2

    def test_text_concatenates_whisper_padding(self):
        t = Transcript.from_words([(" Hello", 0, 1), (" world", 1, 2)])
        assert t.text == "Hello world"

    def test_find_ignores_punctuation_and_case(self):
        t = Transcript.from_words([("Um,", 0, 1), ("UM", 1, 2), ("okay", 2, 3)])
        assert t.find("um") == [0, 1]

    def test_indices_for_text_matches_a_phrase(self):
        t = make_transcript(FIVE)
        assert t.indices_for_text("my name") == [1, 2]

    def test_indices_for_text_absent_phrase(self):
        assert make_transcript(FIVE).indices_for_text("not here") == []

    def test_from_whisper_words_accepts_dicts(self):
        t = Transcript.from_whisper_words(
            [{"word": "hi", "start": 0.0, "end": 0.5}], language="hi"
        )
        assert t[0].text == "hi" and t.language == "hi"

    def test_from_whisper_words_requires_timestamps(self):
        with pytest.raises(TranscriptError, match="missing a timestamp"):
            Transcript.from_whisper_words([{"word": "hi"}])

    def test_empty_transcript(self):
        t = Transcript(words=[])
        assert t.text == "" and t.start == 0.0 and t.end == 0.0 and len(t) == 0


# ── The engine: kept_segments ────────────────────────────────────────────────

class TestKeptSegments:
    def test_nothing_deleted_keeps_the_whole_clip(self):
        t = make_transcript(FIVE, duration=5.0)
        segs = kept_segments(t, [])
        assert segs == [Segment(0.0, 5.0)]

    def test_deleting_a_middle_word_splits_the_timeline(self):
        t = make_transcript(FIVE, duration=5.0)
        segs = kept_segments(t, [2])  # cut "name" (2.0-3.0)
        assert segs == [Segment(0.0, 2.0), Segment(3.0, 5.0)]

    def test_deleting_consecutive_words_makes_one_cut(self):
        t = make_transcript(FIVE, duration=5.0)
        segs = kept_segments(t, [1, 2])  # cut "my name"
        assert segs == [Segment(0.0, 1.0), Segment(3.0, 5.0)]

    def test_deleting_first_word(self):
        t = make_transcript(FIVE, duration=5.0)
        segs = kept_segments(t, [0], preserve_leading=False)
        assert segs == [Segment(1.0, 5.0)]

    def test_preserve_leading_keeps_intro_silence(self):
        t = make_transcript(FIVE, duration=5.0)
        segs = kept_segments(t, [0], preserve_leading=True)
        assert segs == [Segment(0.0, 5.0)]

    def test_deleting_last_word_with_trailing_preserved(self):
        t = make_transcript(FIVE, duration=6.0)  # 1s of trailing silence
        segs = kept_segments(t, [4], preserve_trailing=True)
        assert segs[-1].end == 6.0

    def test_deleting_last_word_without_trailing(self):
        t = make_transcript(FIVE, duration=6.0)
        segs = kept_segments(t, [4], preserve_trailing=False)
        assert segs[-1].end == 4.0

    def test_deleting_everything_returns_empty(self):
        """Returning the full timeline here would silently export the unedited file."""
        t = make_transcript(FIVE, duration=5.0)
        assert kept_segments(t, [0, 1, 2, 3, 4]) == []

    def test_empty_transcript_returns_empty(self):
        assert kept_segments(Transcript(words=[]), []) == []

    def test_out_of_range_index_raises(self):
        t = make_transcript(FIVE)
        with pytest.raises(TranscriptError, match="out of range"):
            kept_segments(t, [99])

    def test_non_int_index_raises(self):
        t = make_transcript(FIVE)
        with pytest.raises(TranscriptError, match="must be an int"):
            kept_segments(t, ["1"])

    def test_duplicate_indices_are_not_double_counted(self):
        t = make_transcript(FIVE, duration=5.0)
        assert kept_segments(t, [2, 2, 2]) == kept_segments(t, [2])

    def test_natural_pause_between_kept_words_survives(self):
        """The whole reason this tool sounds natural."""
        t = make_transcript(
            [("hello", 0.0, 1.0), ("um", 1.5, 2.0), ("world", 2.5, 3.5)], duration=3.5
        )
        segs = kept_segments(t, [1])
        # "hello" and "world" are not consecutive any more, so they split.
        assert segs == [Segment(0.0, 1.0), Segment(2.5, 3.5)]

    def test_max_gap_splits_long_silences(self):
        t = make_transcript(
            [
                ("a", 0.0, 1.0),
                ("b", 4.0, 5.0),   # 3s of silence before this
                ("c", 5.0, 6.0),
            ],
            duration=6.0,
        )
        segs = kept_segments(t, [], max_gap=1.0)
        assert segs == [Segment(0.0, 1.0), Segment(4.0, 6.0)]

    def test_max_gap_none_keeps_the_silence(self):
        t = make_transcript([("a", 0.0, 1.0), ("b", 4.0, 5.0)], duration=5.0)
        assert kept_segments(t, []) == [Segment(0.0, 5.0)]

    def test_float_noise_does_not_create_junk_clips(self):
        # 0.1+0.2 != 0.3 in floats; the engine must snap to milliseconds.
        t = make_transcript([("a", 0.0, 0.1), ("b", 0.1, 0.30000000000000004)])
        segs = kept_segments(t, [])
        assert segs == [Segment(0.0, 0.3)]

    def test_hinglish_transcript(self):
        t = make_transcript(
            [
                ("kaise", 0.0, 0.4),
                ("ho", 0.4, 0.7),
                ("bhai", 0.7, 1.2),
                ("log", 1.2, 1.6),
            ],
            duration=1.6,
        )
        segs = kept_segments(t, [1])  # cut the "ho" filler
        assert segs == [Segment(0.0, 0.4), Segment(0.7, 1.6)]


# ── Inverse + summaries ──────────────────────────────────────────────────────

class TestInverseAndSummaries:
    def test_removed_is_the_complement_of_kept(self):
        t = make_transcript(FIVE, duration=5.0)
        assert removed_segments(t, [2]) == [Segment(2.0, 3.0)]

    def test_kept_plus_removed_covers_the_timeline(self):
        t = make_transcript(FIVE, duration=5.0)
        for deleted in ([], [0], [4], [1, 2], [0, 2, 4]):
            kept = kept_segments(t, deleted)
            removed = removed_segments(t, deleted)
            total = sum(s.duration for s in kept) + sum(s.duration for s in removed)
            assert round(total, 3) == 5.0, f"deleted={deleted} lost media"

    def test_cut_duration(self):
        t = make_transcript(FIVE, duration=5.0)
        assert cut_duration(t, [1, 2]) == 2.0

    def test_deleted_word_count_dedupes(self):
        t = make_transcript(FIVE)
        assert edits.deleted_word_count(t, [1, 1, 2]) == 2

    def test_merge_segments(self):
        merged = merge_segments([Segment(0, 1), Segment(1, 2), Segment(5, 6)])
        assert merged == [Segment(0, 2), Segment(5, 6)]

    def test_merge_handles_unsorted_input(self):
        assert merge_segments([Segment(5, 6), Segment(0, 1)]) == [
            Segment(0, 1),
            Segment(5, 6),
        ]

    def test_segment_rejects_inverted_range(self):
        with pytest.raises(TranscriptError):
            Segment(5.0, 1.0)


# ── Re-timing subtitles after a cut ──────────────────────────────────────────

class TestReindex:
    def test_words_before_the_cut_do_not_move(self):
        t = make_transcript(FIVE, duration=5.0)
        new = reindex_after_cut(t, [2])
        assert (new[0].start, new[0].end) == (0.0, 1.0)
        assert (new[1].start, new[1].end) == (1.0, 2.0)

    def test_words_after_the_cut_shift_earlier(self):
        t = make_transcript(FIVE, duration=5.0)
        new = reindex_after_cut(t, [2])  # removed 2.0-3.0 (1 second)
        # "is" was 3.0-4.0, should become 2.0-3.0
        assert (new[2].start, new[2].end) == (2.0, 3.0)
        # "chirag" was 4.0-5.0, should become 3.0-4.0
        assert (new[3].start, new[3].end) == (3.0, 4.0)

    def test_deleted_words_are_gone(self):
        t = make_transcript(FIVE, duration=5.0)
        new = reindex_after_cut(t, [2])
        assert [w.text for w in new] == ["hello", "my", "is", "chirag"]

    def test_reindexed_words_never_go_backwards(self):
        t = make_transcript(FIVE, duration=5.0)
        new = reindex_after_cut(t, [0, 2, 4])
        for a, b in zip(new, new[1:]):
            assert b.start >= a.start


# ── ffmpeg plan ──────────────────────────────────────────────────────────────

class TestFFmpegPlan:
    def test_concat_file_format(self):
        body = build_concat_file([Segment(0.0, 2.0), Segment(3.0, 5.0)], "in.mp4")
        assert body.startswith("ffconcat version 1.0")
        assert "file 'in.mp4'" in body
        assert "inpoint 0.000" in body
        assert "outpoint 2.000" in body
        assert "inpoint 3.000" in body

    def test_concat_file_escapes_apostrophes(self):
        """A path like "Chirag's demo.mp4" breaks the demuxer if unescaped."""
        body = build_concat_file([Segment(0.0, 1.0)], "Chirag's demo.mp4")
        assert "Chirag'\\''s demo.mp4" in body

    def test_concat_file_rejects_empty(self):
        with pytest.raises(FFmpegPlanError, match="no segments"):
            build_concat_file([], "in.mp4")

    def test_plan_is_runnable(self):
        plan = build_plan([Segment(0.0, 2.0)], "in.mp4", "out.mp4")
        assert plan.args[0] == "ffmpeg"
        assert "-f" in plan.args and "concat" in plan.args
        assert plan.args[-1] == "out.mp4"
        assert plan.total_duration == 2.0

    def test_plan_command_is_shell_quoted(self):
        plan = build_plan([Segment(0.0, 2.0)], "my clip.mp4", "out.mp4")
        assert "my clip.mp4" not in plan.command or "'my clip.mp4'" in plan.command

    def test_audio_only_plan_drops_video_codec(self):
        plan = build_plan([Segment(0, 1)], "in.wav", "out.wav", audio_only=True)
        assert "-vn" in plan.args

    def test_stream_copy_refuses_video(self):
        """Stream copy can only cut on keyframes — silently mis-cutting is worse."""
        with pytest.raises(FFmpegPlanError, match="keyframe"):
            build_plan([Segment(0, 1)], "in.mp4", "out.mp4", copy_codecs=True)

    def test_stream_copy_allowed_for_audio(self):
        plan = build_plan(
            [Segment(0, 1)], "in.wav", "out.wav", audio_only=True, copy_codecs=True
        )
        assert "copy" in plan.args

    def test_trim_filters_chain(self):
        filt = build_trim_filters([Segment(0.0, 1.0), Segment(2.0, 3.0)])
        assert "trim=start=0.000:end=1.000" in filt
        assert "concat=n=2:v=1:a=1[outv][outa]" in filt

    def test_trim_filters_rejects_empty(self):
        with pytest.raises(FFmpegPlanError):
            build_trim_filters([])


# ── SRT rebuild ──────────────────────────────────────────────────────────────

from bolcut.core.srt import build_srt, format_timestamp, parse_timestamp
from bolcut.core.fillers import find_fillers, most_repeated, DEFAULT_FILLERS


class TestSRT:
    def test_timestamp_uses_comma_not_dot(self):
        """SRT requires HH:MM:SS,mmm — a dot breaks most players."""
        assert format_timestamp(3661.5) == "01:01:01,500"

    def test_timestamp_zero(self):
        assert format_timestamp(0) == "00:00:00,000"

    def test_timestamp_never_negative(self):
        assert format_timestamp(-1.0) == "00:00:00,000"

    def test_parse_round_trip(self):
        for value in (0.0, 1.5, 59.999, 3600.0, 3661.5):
            assert parse_timestamp(format_timestamp(value)) == pytest.approx(value, abs=0.001)

    def test_parse_accepts_both_separators(self):
        assert parse_timestamp("00:01:02,500") == parse_timestamp("00:01:02.500")

    def test_parse_short_forms(self):
        assert parse_timestamp("01:30") == 90.0
        assert parse_timestamp("45.5") == 45.5

    def test_parse_rejects_garbage(self):
        with pytest.raises(ValueError, match="cannot parse"):
            parse_timestamp("not a timestamp")

    def test_build_srt_numbering_and_grouping(self):
        words = [Word(f"w{i}", float(i), float(i + 1)) for i in range(10)]
        srt = build_srt(words, lines_per_cue=4)
        assert srt.startswith("1\n00:00:00,000 --> ")
        assert "\n2\n" in srt and "\n3\n" in srt
        assert srt.count("-->") == 3  # 10 words / 4 per cue

    def test_build_srt_empty(self):
        assert build_srt([]) == ""

    def test_srt_for_edited_file_is_shorter(self):
        t = make_transcript(FIVE, duration=5.0)
        original = build_srt(t.words)
        edited = build_srt(reindex_after_cut(t, [2]))
        assert len(edited) < len(original)
        assert "name" not in edited


# ── Fillers ──────────────────────────────────────────────────────────────────

class TestFillers:
    def test_finds_english_fillers(self):
        t = make_transcript([("um", 0, 1), ("hello", 1, 2), ("uh", 2, 3)])
        assert find_fillers(t) == [0, 2]

    def test_finds_hinglish_fillers(self):
        t = make_transcript([("arre", 0, 1), ("bhai", 1, 2), ("matlab", 2, 3)])
        assert find_fillers(t) == [0, 2]

    def test_ignores_punctuation(self):
        t = make_transcript([("Um,", 0, 1), ("hello", 1, 2)])
        assert find_fillers(t) == [0]

    def test_case_insensitive(self):
        t = make_transcript([("UM", 0, 1), ("Uh", 1, 2)])
        assert find_fillers(t) == [0, 1]

    def test_custom_list(self):
        t = make_transcript([("basically", 0, 1), ("hello", 1, 2)])
        assert find_fillers(t, ["basically"]) == [0]

    def test_does_not_flag_real_words(self):
        """'like' and 'so' are usually real words, not fillers."""
        t = make_transcript([("like", 0, 1), ("so", 1, 2), ("this", 2, 3)])
        assert find_fillers(t) == []

    def test_most_repeated_finds_a_tic(self):
        t = make_transcript(
            [("basically", 0, 1), ("hello", 1, 2), ("basically", 2, 3), ("basically", 3, 4)]
        )
        top = most_repeated(t, limit=3)
        assert top[0] == ("basically", 3)

    def test_most_repeated_skips_single_chars(self):
        t = make_transcript([("a", 0, 1), ("I", 1, 2), ("hello", 2, 3)])
        words = [w for w, _ in most_repeated(t)]
        assert "a" not in words and "i" not in words

    def test_default_fillers_are_all_lowercase(self):
        assert all(f == f.lower() for f in DEFAULT_FILLERS)
