"""
ffmpeg runner. Thin wrapper around the plan the core builds.

NOTE: the pure planning logic lives in bolcut.core.ffmpeg_plan and is fully
unit-tested. This module only shells out, so it has no logic to get wrong.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..core.ffmpeg_plan import FFmpegPlan


class FFmpegError(RuntimeError):
    """Raised when ffmpeg is missing or exits non-zero."""


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FFmpegError(
            "ffmpeg not found on PATH.\n"
            "  macOS:   brew install ffmpeg\n"
            "  Ubuntu:  sudo apt install ffmpeg\n"
            "  Windows: winget install Gyan.FFmpeg"
        )
    return path


def run_plan(plan: FFmpegPlan, *, concat_file: str | Path, dry_run: bool = False) -> int:
    """Write the concat file and run ffmpeg. Returns ffmpeg's exit code."""
    concat_path = Path(concat_file)
    concat_path.write_text(plan.concat_file_body, encoding="utf-8")

    if dry_run:
        print(plan.command)
        return 0

    require_ffmpeg()
    result = subprocess.run(plan.args, check=False)
    if result.returncode != 0:
        raise FFmpegError(f"ffmpeg exited with code {result.returncode}")

    concat_path.unlink(missing_ok=True)
    return result.returncode
