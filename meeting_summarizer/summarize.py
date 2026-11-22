"""Step 3 - structured meeting summary with Gemini Flash (free tier).

Two design choices replace most of the old notebook:
- The WHOLE transcript goes in one request (Flash has a ~1M-token context; a 1 h
  meeting is ~20k tokens). No chunking, no consolidation step, no truncation.
- Structured output: we pass a Pydantic schema and Gemini returns JSON that
  matches it. No regex parsing of free text.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# Google retires model versions often (gemini-2.5-flash already returns 404 for
# new accounts). So this is a comma-separated FALLBACK CHAIN: if a model is gone
# (404) the next one is tried. Override with the GEMINI_MODEL setting.
# Quality first: in a side-by-side review 3.8-flash wrote clearly richer topic
# descriptions than 3.5-flash. The trade-off is latency on the free tier
# (3.8: ~60 s, sometimes several minutes when queued; 3.5: ~20 s).
DEFAULT_MODEL = "gemini-3.8-flash,gemini-3.7-flash,gemini-3.5-flash"


class Topic(BaseModel):
    title: str = Field(description="Short name of the topic")
    description: str = Field(description="2 to 4 sentences on what was said about the topic")
    start: str = Field(description="HH:MM:SS timestamp where the topic started being discussed")


class ActionItem(BaseModel):
    owner: str = Field(description="Who will do it, or 'Not specified'")
    task: str
    due: str = Field(description="Deadline mentioned, or 'Not specified'")


class MeetingSummary(BaseModel):
    language: str = Field(description="ISO 639-1 code of the language spoken in the meeting, e.g. 'pt' or 'en'")
    title: str = Field(description="Descriptive title of the meeting")
    executive_summary: str = Field(description="2 to 3 paragraphs separated by a blank line")
    topics: list[Topic] = Field(description="Main topics, in chronological order")
    decisions: list[str]
    action_items: list[ActionItem]
    risks: list[str] = Field(description="Risks and points of attention")
    open_questions: list[str] = Field(description="Questions or subjects left open")


SYSTEM_INSTRUCTION = (
    "You are an experienced meeting analyst. Use ONLY what is explicit in the transcript. "
    "Do not invent facts, decisions, owners, deadlines or risks: if something was not said, "
    "return an empty list or 'Not specified'. Group everything said about the same subject "
    "into a single topic; ignore small talk and logistics with no content. "
    "Write every text field in the SAME language spoken in the meeting (translate 'Not specified' too)."
)


def build_prompt(transcript: str, glossary: list[str]) -> str:
    # Note: no example topics here. The prototype's prompt listed example topics,
    # which made the model "find" those topics in every meeting.
    glossary_line = f"Correct spelling of proper names: {', '.join(glossary)}.\n" if glossary else ""
    return (
        "Analyse the meeting transcript below (each line starts with its timestamp).\n"
        "It is an automatic transcript and may misspell names; fix them when the context makes it clear.\n"
        f"{glossary_line}\n"
        f"<transcript>\n{transcript}\n</transcript>"
    )


def parse_response(resp: Any) -> MeetingSummary:
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, MeetingSummary):
        return parsed
    return MeetingSummary.model_validate_json(resp.text)


def summarize(
    transcript: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    glossary: list[str] | None = None,
) -> MeetingSummary:
    # Imported here so the rest of the package (and the tests) load fast.
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        # Free tier returns 429 when you go over the per-minute quota; retry with
        # exponential backoff instead of failing immediately.
        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=4, initial_delay=2.0)),
    )
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_schema=MeetingSummary,
        temperature=0.2,  # low = faithful to the transcript, little "creativity"
    )
    return generate_with_fallback(client, model_chain(model), build_prompt(transcript, glossary or []), config)


def model_chain(model: str) -> list[str]:
    return [m.strip() for m in model.split(",") if m.strip()]


def generate_with_fallback(client: Any, models: list[str], prompt: str, config: Any) -> MeetingSummary:
    """Try each model in order; move on ONLY when the model no longer exists (404).

    Other errors (invalid key, quota) would fail on every model too, so they are
    raised immediately instead of wasting calls.
    """
    for i, model in enumerate(models):
        try:
            return parse_response(client.models.generate_content(model=model, contents=prompt, config=config))
        except Exception as exc:
            if getattr(exc, "code", None) != 404 or i == len(models) - 1:
                raise
    raise ValueError("No Gemini model configured.")
