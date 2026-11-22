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
    title: str = Field(description="Specific name of the topic (include the programme/partner/project name)")
    # Field descriptions are part of the prompt: the old "2 to 4 sentences" capped
    # the level of detail. Asking for concrete details made summaries ~40% richer.
    description: str = Field(
        description="3 to 6 sentences: who presented it, what was said, and every concrete detail "
        "mentioned (names, numbers, dates, places, deadlines, outcomes)"
    )
    start: str = Field(description="HH:MM:SS timestamp where the topic started being discussed")


class ActionItem(BaseModel):
    owner: str = Field(description="Who will do it, or 'Not specified'")
    task: str = Field(description="Concrete task, with any detail mentioned (what, for whom, where)")
    due: str = Field(description="Deadline mentioned, or 'Not specified'")


class MeetingSummary(BaseModel):
    language: str = Field(description="ISO 639-1 code of the language spoken in the meeting, e.g. 'pt' or 'en'")
    title: str = Field(description="Descriptive title of the meeting")
    executive_summary: str = Field(
        description="3 to 4 paragraphs separated by a blank line, naming the people, partners, "
        "programmes, numbers and dates that matter"
    )
    topics: list[Topic] = Field(description="Every distinct subject discussed, in chronological order")
    decisions: list[str]
    action_items: list[ActionItem] = Field(description="Every commitment, request or next step mentioned")
    risks: list[str] = Field(description="Risks and points of attention")
    open_questions: list[str] = Field(description="Questions or subjects left open")


SYSTEM_INSTRUCTION = (
    "You are an experienced meeting analyst. Use ONLY what is explicit in the transcript. "
    "Do not invent facts, decisions, owners, deadlines or risks: if something was not said, "
    "return an empty list or 'Not specified'. Group everything said about the same subject "
    "into a single topic; ignore small talk and logistics with no content. "
    "Be specific and complete: keep the names of people, organisations and programmes, and every number, "
    "date and deadline mentioned. Give each distinct subject its own topic instead of merging unrelated "
    "subjects; a reader who missed the meeting must not lose any relevant detail. "
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
) -> tuple[MeetingSummary, str]:
    """Returns the summary and the name of the model that produced it."""
    # Imported here so the rest of the package (and the tests) load fast.
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        # One quick retry for transient errors; after that it is faster to move on
        # to the next model in the chain than to keep waiting on a busy one.
        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=2, initial_delay=2.0)),
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


# 404 = model retired, 429 = this model's quota is used up (free-tier quotas are
# per model), 503 = model overloaded ("high demand"). In all three cases another
# model can still answer. Errors like an invalid key (400/401/403) would fail on
# every model, so they are raised immediately.
FALLBACK_CODES = {404, 429, 503}


def generate_with_fallback(client: Any, models: list[str], prompt: str, config: Any) -> tuple[MeetingSummary, str]:
    """Try each model in order, moving on only for errors another model can avoid."""
    for i, model in enumerate(models):
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=config)
            return parse_response(resp), model
        except Exception as exc:
            if getattr(exc, "code", None) not in FALLBACK_CODES or i == len(models) - 1:
                raise
    raise ValueError("No Gemini model configured.")
