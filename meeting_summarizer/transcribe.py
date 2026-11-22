"""Step 2 - speech-to-text with Whisper large-v3 on Groq's free tier.

Groq runs Whisper on dedicated hardware, so a 1 h meeting transcribes in
seconds instead of the ~3 min the local Colab T4 needed (and with the large-v3
model instead of a smaller local one).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "whisper-large-v3"
# Whisper treats the prompt as "previous text": it biases spelling of names
# (e.g. an organisation's acronym transcribed as a similar-sounding word).
# Groq caps it at 224 tokens, so keep it short.
_PROMPT_MAX_CHARS = 600
# Segments Whisper itself flags as probably-silence: dropping them removes
# classic hallucinations like "Legendas pela comunidade Amara.org".
_NO_SPEECH_THRESHOLD = 0.8


@dataclass(frozen=True)
class Segment:
    start: float  # seconds from the start of the meeting
    end: float
    text: str


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """The SDK may hand back dicts or objects depending on version - accept both."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def build_whisper_prompt(glossary: list[str]) -> str:
    return (", ".join(glossary) + ".")[:_PROMPT_MAX_CHARS] if glossary else ""


def transcribe_part(
    client: Any, path: Path, offset: float, model: str, prompt: str, language: str | None = "pt"
) -> list[Segment]:
    options: dict[str, Any] = {
        "response_format": "verbose_json",  # gives per-segment timestamps
        "temperature": 0.0,  # deterministic output
    }
    if language:  # a fixed language skips auto-detection: faster and no mis-detection
        options["language"] = language
    if prompt:
        options["prompt"] = prompt
    resp = client.audio.transcriptions.create(file=(path.name, path.read_bytes()), model=model, **options)
    raw_segments = _get(resp, "segments") or []
    if not raw_segments:  # fallback: plain text only
        text = (_get(resp, "text") or "").strip()
        return [Segment(offset, offset, text)] if text else []

    segments = []
    for s in raw_segments:
        text = (_get(s, "text") or "").strip()
        if not text or (_get(s, "no_speech_prob") or 0.0) > _NO_SPEECH_THRESHOLD:
            continue
        # Each part restarts at 0 s, so shift by the part's position in the meeting.
        segments.append(Segment(offset + float(_get(s, "start", 0.0)), offset + float(_get(s, "end", 0.0)), text))
    return segments


def transcribe_parts(
    client: Any,
    parts: list[Path],
    segment_seconds: int,
    model: str = DEFAULT_MODEL,
    glossary: list[str] | None = None,
    language: str | None = "pt",
    max_workers: int = 4,
) -> list[Segment]:
    """Transcribe all parts in parallel and return segments in meeting order.

    Threads are the right tool here: the work is waiting on the network, not CPU.
    max_workers=4 stays well under the free tier's requests-per-minute limit.
    """
    prompt = build_whisper_prompt(glossary or [])
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(parts)))) as pool:
        futures = [
            pool.submit(transcribe_part, client, part, i * segment_seconds, model, prompt, language)
            for i, part in enumerate(parts)
        ]
        # Collecting in submission order keeps the timeline correct even though
        # parts may finish out of order.
        results = [f.result() for f in futures]
    return [seg for part_segments in results for seg in part_segments]


def hhmmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def format_transcript(segments: list[Segment]) -> str:
    """'[00:01:23] text' lines - timestamps let the LLM say when each topic was discussed."""
    return "\n".join(f"[{hhmmss(s.start)}] {s.text}" for s in segments)
