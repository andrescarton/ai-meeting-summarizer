# AI Meeting Summarizer

**[Live app](https://ai-meeting-summarizer-3nhlkosavbvviawysjhfsq.streamlit.app/)**

Upload a meeting recording (video or audio) and get a Word document with an executive summary, the main topics with timestamps, decisions, action items with owners and deadlines, risks and open questions. The summary is written in the language of the meeting.

This was a deliverable for the non-profit where I volunteer. They record their monthly meetings and wanted minutes written automatically, with one hard requirement: **it had to cost nothing**. So everything runs on free tiers: Whisper on Groq for the transcription, Google Gemini for the summary and Streamlit Community Cloud for the app.

New to the project? [The story behind it](docs/PROJECT_STORY.md) walks through what I did and why, in plain language.

## How it works

```
recording (.mp4 / .mp3 / .m4a ...)
   ▼  audio.py        ffmpeg drops the video, keeps mono 16 kHz speech, splits into 15-min parts
   ▼  transcribe.py   Whisper large-v3 on Groq, parts in parallel, timestamps kept
   ▼  summarize.py    Gemini reads the whole transcript and fills a Pydantic schema (JSON)
   ▼  docx_report.py  python-docx builds the report in memory
minutes (.docx)
```

## What I did

- Started from my own Colab prototype (local Whisper + Llama 3.1 8B on a T4) that worked but took 18.5 minutes for a 10-minute meeting and needed a GPU, so it could never be deployed for free
- Moved the heavy models to free APIs and kept only light work (ffmpeg, python-docx) in the app
- Compressed the audio to what Whisper actually uses (mono, 16 kHz, 32 kbps): a 738 MB video becomes a 2.4 MB file, so long meetings stay under Groq's 25 MB limit
- Sent the whole transcript to Gemini in one request instead of summarising 2-minute chunks and merging them, which is what made the prototype's topics vague
- Replaced regex parsing of free text with structured output against a Pydantic schema
- Added a glossary of names and acronyms that goes to both Whisper and Gemini, because speech-to-text kept misspelling the organisation's name
- Benchmarked the Gemini models and prompts on the same transcript before choosing defaults
- Made the app survive the free tier: falls back to another model when one is retired (404), out of quota (429) or overloaded (503)
- Unit tests with the APIs mocked, so CI on GitHub Actions needs no keys and costs nothing

## Results

On a 10-minute sample meeting:

| | Colab prototype | This app |
|---|---|---|
| Audio extraction | 31.9 s | 2.3 s |
| Transcription | 180.9 s (incl. model load) | 4.7 s |
| Summary | 900.4 s (chunks + merge) | ~25 s (*Fast*) to 1–5 min (*Best quality*) |
| Organisation name spelled right | 0 of 4 times | every time (glossary) |
| Topics | generic ("Questions", "Activities") | specific, with who presented and what was said |
| Cost | Colab GPU | $0 |

### Prompt beats model

The first version asked for "2 to 4 sentences" per topic and the summaries came out thin. Asking for who presented each topic and every name, number, date and deadline changed more than switching models did. Same transcript, temperature 0.2:

| Model | Prompt | Time | Words | Topics |
|---|---|---|---|---|
| gemini-3.5-flash | short | 16 s | 626 | 7 |
| gemini-3.8-flash | short | 157 s | 742 | 6 |
| gemini-3.5-flash | **detailed** | **26 s** | **1,035** | **9** |

Reading the outputs side by side, 3.8 still writes the most polished descriptions, so it is the default (*Best quality*). It queues on the free tier, though, sometimes for minutes, so the sidebar also offers *Fast* (3.5).

## Files

- `app.py` – Streamlit app: upload, settings in the sidebar, summary tabs and the .docx download
- `meeting_summarizer/audio.py` – audio extraction and splitting with a bundled ffmpeg (`imageio-ffmpeg`)
- `meeting_summarizer/transcribe.py` – parallel Whisper transcription with timestamps
- `meeting_summarizer/summarize.py` – Pydantic schema, prompt and the Gemini model fallback
- `meeting_summarizer/docx_report.py` – the Word report, headings in the meeting's language
- `meeting_summarizer/pipeline.py` – runs the four steps, times them, and works as a CLI
- `tests/` – 22 tests, APIs mocked

## Running it

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # add your two free keys
streamlit run app.py
```

Free keys: Groq at <https://console.groq.com/keys>, Gemini at <https://aistudio.google.com/apikey>. No system ffmpeg needed.

From the command line:

```bash
python -m meeting_summarizer.pipeline meeting.mp4 -o minutes.docx
python -m meeting_summarizer.pipeline meeting.mp4 --audio-only -o meeting.mp3   # shrink a big video first
```

Tests: `pip install -r requirements-dev.txt`, then `ruff check . && pytest`.

## Limits

- 10 minutes of 1080p video is ~740 MB. The app accepts up to 800 MB, but for long meetings upload the audio (Zoom, Meet and Teams can export it): an hour of speech is ~15 MB.
- Free tiers cap requests per minute and per day. Fine for a few meetings a day.
- On Gemini's free tier Google may use what you send to improve its products. For confidential meetings use a paid tier.
- It's an AI summary: someone should read it before it goes out.
