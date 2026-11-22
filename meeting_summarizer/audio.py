"""Step 1 - extract a small, speech-optimised audio track with ffmpeg.

Why these settings:
- mono, 16 kHz: Whisper resamples everything to 16 kHz mono internally, so
  sending more is wasted upload time.
- 32 kbps MP3: ~14 MB per hour of speech, well below Groq's 25 MB free-tier
  file limit, with no measurable loss in transcription quality for speech.
- split into fixed-length parts in the SAME ffmpeg pass: long meetings never hit
  the file limit, and the parts can be transcribed in parallel.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg

SEGMENT_SECONDS = 900  # 15 min per part -> ~3.6 MB each

_AUDIO_ARGS = ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k"]


class AudioError(RuntimeError):
    """ffmpeg failed or the file has no audio track."""


def ffmpeg_exe() -> str:
    # imageio-ffmpeg ships a static ffmpeg binary inside the pip package, so the
    # same code works on Windows, macOS, Linux and Streamlit Cloud with no
    # system install.
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise AudioError(f"ffmpeg failed: {result.stderr.strip()[-500:]}")


def extract_audio_parts(input_path: Path, out_dir: Path, segment_seconds: int = SEGMENT_SECONDS) -> list[Path]:
    """Decode the input once and write part_000.mp3, part_001.mp3, ..."""
    out_dir.mkdir(parents=True, exist_ok=True)
    _run([
        ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(input_path),
        *_AUDIO_ARGS,
        "-f", "segment", "-segment_time", str(segment_seconds), "-reset_timestamps", "1",
        str(out_dir / "part_%03d.mp3"),
    ])
    parts = sorted(out_dir.glob("part_*.mp3"))
    if not parts:
        raise AudioError("No audio track found in the file.")
    return parts


def compress_audio(input_path: Path, output_path: Path) -> Path:
    """Single-file version, used by the CLI to shrink a big video before uploading it."""
    _run([
        ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(input_path), *_AUDIO_ARGS, str(output_path),
    ])
    return output_path
