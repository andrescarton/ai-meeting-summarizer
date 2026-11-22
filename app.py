"""Streamlit front-end: upload a meeting recording, get a summary .docx."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import streamlit as st

from meeting_summarizer import pipeline, summarize, transcribe
from meeting_summarizer.docx_report import build_docx

st.set_page_config(page_title="AI Meeting Summarizer", page_icon="📝", layout="centered")


def get_setting(name: str, default: str = "") -> str:
    """Streamlit Cloud -> st.secrets; local runs -> .streamlit/secrets.toml or env vars."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets.toml at all
        pass
    return os.environ.get(name, default)


def friendly_error(exc: Exception) -> str:
    name = type(exc).__name__
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if name == "RateLimitError" or code == 429:
        return "Free API quota reached. Wait a few minutes and try again."
    if name in {"AuthenticationError", "PermissionDeniedError"} or code in {401, 403}:
        return "Invalid API key. Check GROQ_API_KEY and GEMINI_API_KEY in the app Secrets."
    if code == 413 or "too large" in str(exc).lower():
        return "Audio part too large for Groq's free tier."
    return f"Unexpected error ({name}): {exc}"


def bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) or "_None._"


GROQ_KEY = get_setting("GROQ_API_KEY")
GEMINI_KEY = get_setting("GEMINI_API_KEY")

st.title("📝 AI Meeting Summarizer")
st.caption("Upload a meeting recording and get a document with an executive summary, topics, decisions and actions.")

with st.sidebar:
    st.header("Settings")
    meeting_language = st.selectbox(
        "Meeting language",
        list(pipeline.MEETING_LANGUAGES),
        help="The summary is written in the same language as the meeting.",
    )
    glossary_text = st.text_area(
        "Glossary (one term per line)",
        "\n".join(pipeline.DEFAULT_GLOSSARY),
        help="Proper names and acronyms used in the meeting (organisation, partners, people). "
        "Helps Whisper and Gemini spell them correctly.",
        height=160,
    )
    include_transcript = st.checkbox("Append transcript to the document", value=True)
    st.divider()
    st.caption(
        "Tip: HD videos are huge (10 min of 1080p ≈ 700 MB). Upload just the audio "
        "(.mp3/.m4a) whenever possible: it uploads in seconds."
    )

if not (GROQ_KEY and GEMINI_KEY):
    st.warning("Set GROQ_API_KEY and GEMINI_API_KEY in `.streamlit/secrets.toml` (local) or in the app Secrets.")
    st.stop()

uploaded = st.file_uploader("Meeting recording", type=["mp3", "m4a", "wav", "ogg", "webm", "mp4", "mov", "mkv"])
glossary = [t.strip() for t in glossary_text.splitlines() if t.strip()]

# Streamlit re-runs this whole script on EVERY interaction (even clicking
# "download"). Keeping the result in session_state, keyed by the upload and the
# settings, means the APIs are called once per file instead of once per click.
run_key = (uploaded.file_id, tuple(glossary), meeting_language) if uploaded else None

if uploaded and st.button("Summarize meeting", type="primary", use_container_width=True):
    with st.status("Processing the meeting...", expanded=True) as status:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                # ffmpeg needs a real file path, so the upload is written to disk.
                input_path = Path(tmp) / Path(uploaded.name).name
                input_path.write_bytes(uploaded.getbuffer())
                result = pipeline.run(
                    input_path,
                    groq_api_key=GROQ_KEY,
                    gemini_api_key=GEMINI_KEY,
                    glossary=glossary,
                    meeting_language=pipeline.MEETING_LANGUAGES[meeting_language],
                    whisper_model=get_setting("WHISPER_MODEL", transcribe.DEFAULT_MODEL),
                    gemini_model=get_setting("GEMINI_MODEL", summarize.DEFAULT_MODEL),
                    progress=st.write,
                )
            st.session_state["result"] = result
            st.session_state["run_key"] = run_key
            status.update(label=f"Done in {result.timings['total_s']:.0f} s", state="complete", expanded=False)
        except Exception as exc:  # show a readable message instead of a stack trace
            status.update(label="Failed", state="error")
            st.error(friendly_error(exc))

result: pipeline.PipelineResult | None = st.session_state.get("result")
if result is None or st.session_state.get("run_key") != run_key:
    st.stop()

summary = result.summary
st.download_button(
    "⬇️ Download document (.docx)",
    data=build_docx(summary, result.segments if include_transcript else None, uploaded.name),
    file_name=f"{Path(uploaded.name).stem}_summary.docx",
    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    type="primary",
    use_container_width=True,
)

tab_summary, tab_actions, tab_transcript, tab_timing = st.tabs(
    ["Summary", "Decisions & actions", "Transcript", "Timings"]
)

with tab_summary:
    st.subheader(summary.title)
    st.markdown(summary.executive_summary)
    st.markdown("#### Main topics")
    for topic in summary.topics:
        with st.expander(f"{topic.title} · {topic.start}"):
            st.write(topic.description)

with tab_actions:
    st.markdown("#### Decisions")
    st.markdown(bullet_list(summary.decisions))
    st.markdown("#### Action items")
    if summary.action_items:
        st.dataframe([a.model_dump() for a in summary.action_items], hide_index=True, use_container_width=True)
    else:
        st.markdown("_None._")
    st.markdown("#### Risks and points of attention")
    st.markdown(bullet_list(summary.risks))
    st.markdown("#### Open questions")
    st.markdown(bullet_list(summary.open_questions))

with tab_transcript:
    st.text_area("Transcript", result.transcript, height=400, label_visibility="collapsed")

with tab_timing:
    st.dataframe(
        [{"step": k, "seconds": round(v, 1)} for k, v in result.timings.items()],
        hide_index=True,
        use_container_width=True,
    )
