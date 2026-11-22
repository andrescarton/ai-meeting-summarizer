"""Glue: runs the 4 steps and times each one. Usable from the Streamlit app or the CLI.

CLI:
    python -m meeting_summarizer.pipeline "meeting.mp4" -o summary.docx         # full pipeline
    python -m meeting_summarizer.pipeline "meeting.mp4" --audio-only -o a.mp3   # just shrink a big video
Keys come from the GROQ_API_KEY and GEMINI_API_KEY environment variables.
"""

from __future__ import annotations

import argparse
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from meeting_summarizer import audio, summarize, transcribe
from meeting_summarizer.docx_report import build_docx

# Empty by default: each team fills in its own names/acronyms in the app sidebar.
DEFAULT_GLOSSARY: list[str] = []

# Whisper language codes. None = let Whisper detect the language.
MEETING_LANGUAGES: dict[str, str | None] = {"Portuguese": "pt", "English": "en", "Auto-detect": None}

# Gemini fallback chains offered in the app. Both use the same detailed prompt.
SUMMARY_MODES: dict[str, str] = {
    "Best quality (~1-5 min)": summarize.DEFAULT_MODEL,
    "Fast (~30 s)": "gemini-3.5-flash,gemini-3.7-flash,gemini-3.8-flash",
}

Progress = Callable[[str], None]


@dataclass
class PipelineResult:
    summary: summarize.MeetingSummary
    segments: list[transcribe.Segment]
    timings: dict[str, float] = field(default_factory=dict)
    model: str = ""  # Gemini model that wrote the summary (after any fallback)

    @property
    def transcript(self) -> str:
        return transcribe.format_transcript(self.segments)


def run(
    input_path: Path,
    groq_api_key: str,
    gemini_api_key: str,
    glossary: list[str] | None = None,
    meeting_language: str | None = "pt",
    whisper_model: str = transcribe.DEFAULT_MODEL,
    gemini_model: str = summarize.DEFAULT_MODEL,
    progress: Progress = lambda _msg: None,
) -> PipelineResult:
    from groq import Groq

    glossary = DEFAULT_GLOSSARY if glossary is None else glossary
    timings: dict[str, float] = {}

    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.perf_counter()
        progress("Extracting and compressing the audio...")
        parts = audio.extract_audio_parts(input_path, Path(tmp))
        timings["audio_extraction_s"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        progress(f"Transcribing {len(parts)} audio part(s) with Whisper...")
        # max_retries: the SDK retries 429/5xx with exponential backoff on its own.
        client = Groq(api_key=groq_api_key, max_retries=4)
        segments = transcribe.transcribe_parts(
            client, parts, audio.SEGMENT_SECONDS, whisper_model, glossary, meeting_language
        )
        timings["transcription_s"] = time.perf_counter() - t0

    if not segments:
        raise ValueError("The transcript is empty: does the file contain audible speech?")

    t0 = time.perf_counter()
    progress("Writing summary, topics and action items with Gemini...")
    result_summary, used_model = summarize.summarize(
        transcribe.format_transcript(segments), gemini_api_key, gemini_model, glossary
    )
    timings["summary_s"] = time.perf_counter() - t0
    timings["total_s"] = sum(timings.values())
    return PipelineResult(result_summary, segments, timings, used_model)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarise a meeting recording (video/audio) into a .docx")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--audio-only", action="store_true", help="only extract/compress the audio to .mp3")
    parser.add_argument("--no-transcript", action="store_true", help="do not append the transcript to the .docx")
    parser.add_argument("--meeting-language", choices=list(MEETING_LANGUAGES), default="Portuguese")
    args = parser.parse_args()

    if args.audio_only:
        out = audio.compress_audio(args.input, args.output or args.input.with_suffix(".mp3"))
        print(f"Audio saved to {out} ({out.stat().st_size / 1e6:.1f} MB)")
        return

    result = run(
        args.input,
        groq_api_key=os.environ["GROQ_API_KEY"],
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        meeting_language=MEETING_LANGUAGES[args.meeting_language],
        whisper_model=os.environ.get("WHISPER_MODEL", transcribe.DEFAULT_MODEL),
        gemini_model=os.environ.get("GEMINI_MODEL", summarize.DEFAULT_MODEL),
        progress=print,
    )
    output = args.output or args.input.with_name(args.input.stem + "_summary.docx")
    segments = None if args.no_transcript else result.segments
    output.write_bytes(build_docx(result.summary, segments, args.input.name))
    for name, seconds in result.timings.items():
        print(f"{name}: {seconds:.1f}")
    print(f"summary model: {result.model}")
    print(f"Document saved to {output}")


if __name__ == "__main__":
    main()
