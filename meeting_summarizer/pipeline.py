"""Glue: runs the 4 steps and times each one. Usable from the Streamlit app or the CLI.

CLI:
    python -m meeting_summarizer.pipeline "reuniao.mp4" -o resumo.docx        # full pipeline
    python -m meeting_summarizer.pipeline "reuniao.mp4" --audio-only -o a.mp3  # just shrink a big video
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

Progress = Callable[[str], None]


@dataclass
class PipelineResult:
    summary: summarize.ResumoReuniao
    segments: list[transcribe.Segment]
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def transcript(self) -> str:
        return transcribe.format_transcript(self.segments)


def run(
    input_path: Path,
    groq_api_key: str,
    gemini_api_key: str,
    glossary: list[str] | None = None,
    whisper_model: str = transcribe.DEFAULT_MODEL,
    gemini_model: str = summarize.DEFAULT_MODEL,
    progress: Progress = lambda _msg: None,
) -> PipelineResult:
    from groq import Groq

    glossary = DEFAULT_GLOSSARY if glossary is None else glossary
    timings: dict[str, float] = {}

    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.perf_counter()
        progress("Extraindo e comprimindo o áudio...")
        parts = audio.extract_audio_parts(input_path, Path(tmp))
        timings["audio_extraction_s"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        progress(f"Transcrevendo {len(parts)} parte(s) de áudio com Whisper...")
        # max_retries: the SDK retries 429/5xx with exponential backoff on its own.
        client = Groq(api_key=groq_api_key, max_retries=4)
        segments = transcribe.transcribe_parts(client, parts, audio.SEGMENT_SECONDS, whisper_model, glossary)
        timings["transcription_s"] = time.perf_counter() - t0

    if not segments:
        raise ValueError("A transcrição ficou vazia: o arquivo tem fala audível?")

    t0 = time.perf_counter()
    progress("Gerando resumo, temas e ações com Gemini...")
    result_summary = summarize.summarize(transcribe.format_transcript(segments), gemini_api_key, gemini_model, glossary)
    timings["summary_s"] = time.perf_counter() - t0
    timings["total_s"] = sum(timings.values())
    return PipelineResult(result_summary, segments, timings)


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume uma reunião (vídeo/áudio) em um .docx")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--audio-only", action="store_true", help="só extrai/comprime o áudio para .mp3")
    parser.add_argument("--no-transcript", action="store_true", help="não anexar a transcrição ao .docx")
    args = parser.parse_args()

    if args.audio_only:
        out = audio.compress_audio(args.input, args.output or args.input.with_suffix(".mp3"))
        print(f"Áudio salvo em {out} ({out.stat().st_size / 1e6:.1f} MB)")
        return

    result = run(
        args.input,
        groq_api_key=os.environ["GROQ_API_KEY"],
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        whisper_model=os.environ.get("WHISPER_MODEL", transcribe.DEFAULT_MODEL),
        gemini_model=os.environ.get("GEMINI_MODEL", summarize.DEFAULT_MODEL),
        progress=print,
    )
    output = args.output or args.input.with_name(args.input.stem + "_resumo.docx")
    output.write_bytes(build_docx(result.summary, None if args.no_transcript else result.segments, args.input.name))
    for name, seconds in result.timings.items():
        print(f"{name}: {seconds:.1f}")
    print(f"Documento salvo em {output}")


if __name__ == "__main__":
    main()
