"""
faster-whisper adapter — the only place that touches a model.

Kept thin on purpose. The engine does not import this, so the whole editing
core stays testable without downloading a model.

Requires:  pip install faster-whisper
"""
from __future__ import annotations

from typing import Any

from ..core.transcript import Transcript

# `large-v3` is the best multilingual model; `small` is the practical default on
# a CPU. Hindi/Hinglish needs at least `small` — `tiny` and `base` mangle it.
DEFAULT_MODEL = "small"


def transcribe(
    path: str,
    *,
    model_size: str = DEFAULT_MODEL,
    language: str | None = None,
    device: str = "auto",
    compute_type: str = "auto",
    word_timestamps: bool = True,
) -> tuple[Transcript, float]:
    """
    Transcribe a media file and return (Transcript, duration_seconds).

    `word_timestamps=True` is not optional in practice — without it there is
    nothing to cut on.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - depends on optional dep
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install faster-whisper"
        ) from exc

    if not word_timestamps:
        raise ValueError("bolcut requires word_timestamps=True to cut media")

    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
        compute_type = "float16" if device == "cuda" else "int8"

    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    segments, info = model.transcribe(
        path,
        language=language,
        word_timestamps=True,
        vad_filter=True,
    )

    words: list[Any] = []
    for segment in segments:
        if segment.words:
            words.extend(segment.words)

    if not words:
        raise RuntimeError(
            f"no words transcribed from {path} — is the file silent, or is the "
            f"model too small for this language?"
        )

    transcript = Transcript.from_whisper_words(
        words, language=info.language, duration=info.duration
    )
    return transcript, info.duration


def transcribe_to_json(path: str, out_path: str, **kwargs) -> str:
    """Transcribe and save the transcript so `bolcut cut` can run offline later."""
    import json

    transcript, duration = transcribe(path, **kwargs)
    payload = {
        "language": transcript.language,
        "duration": duration,
        "words": [
            {"word": w.text, "start": round(w.start, 3), "end": round(w.end, 3)}
            for w in transcript.words
        ],
    }
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return out_path
