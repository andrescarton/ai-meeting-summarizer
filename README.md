# AI Meeting Summarizer

**[Try the live app →](https://ai-meeting-summarizer-3nhlkosavbvviawysjhfsq.streamlit.app/)**

Upload a meeting recording (video or audio) and get a Word document with an executive
summary, main topics (with timestamps), decisions, action items, risks and open questions.
The report is written in the same language as the meeting (Portuguese, English or auto-detect).

This project was a deliverable requested by the non-profit organisation where I volunteer:
they wanted their monthly meeting recordings turned into minutes automatically, **at zero cost**.
It runs entirely on free tiers: Streamlit Community Cloud + Groq (Whisper) + Google Gemini.

## How it works

```
upload (.mp4 / .mp3 / .m4a ...)
   │
   ▼  audio.py        ffmpeg: mono, 16 kHz, 32 kbps MP3, split into 15-min parts (one pass)
   ▼  transcribe.py   Groq Whisper large-v3, parts transcribed in parallel, timestamps kept
   ▼  summarize.py    Gemini Flash reads the WHOLE transcript, returns JSON (Pydantic schema)
   ▼  docx_report.py  python-docx builds the report in memory
download .docx
```

All modules live in `meeting_summarizer/`; `pipeline.py` wires them together and `app.py` is the
Streamlit front-end.

## From prototype to production

The first version (Colab notebook, local Whisper + Llama 3.1 8B on a T4 GPU) worked but could not
be deployed. What changed and why:

| Problem in the prototype | Fix |
|---|---|
| 18.5 min for a 10-min meeting; needed a GPU | Inference moved to free APIs: **~70 s end to end** (audio 2.3 s, transcription 4.6 s, summary ~60 s) |
| 8B model saw 2-min chunks, then a slow consolidation pass produced generic topics ("Questions", "Activities") | Gemini's long context takes the whole meeting in one request: no chunking, no consolidation |
| Executive summary truncated to the first 1,800 words | Whole transcript is used |
| Prompt contained example topics, biasing every summary | Generic prompt + regression test |
| Free-text output parsed with regex | Structured output against a Pydantic schema |
| Organisation and partner names misspelled by speech-to-text | User-editable glossary passed to Whisper (`prompt`) and to Gemini |
| Whisper hallucinations on silence | Segments with `no_speech_prob > 0.8` dropped |
| Model versions retired by the provider break the app | Gemini model fallback chain (on 404 only) |
| Speed vs. quality of the summary model | Benchmarked on the same transcript: gemini-3.5-flash ~20 s, 3.8-flash ~60 s+ but with much richer topic descriptions in user review, so 3.8 goes first |

## Run locally

```bash
pip install -r requirements-dev.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # add your two free keys
streamlit run app.py
```

Free keys: Groq at <https://console.groq.com/keys>, Gemini at <https://aistudio.google.com/apikey>.
No system ffmpeg needed: `imageio-ffmpeg` ships a static binary.

Command line (keys from `GROQ_API_KEY` / `GEMINI_API_KEY`):

```bash
python -m meeting_summarizer.pipeline "meeting.mp4" -o summary.docx
python -m meeting_summarizer.pipeline "meeting.mp4" --audio-only -o meeting.mp3   # shrink a big video first
```

## Deploy (Streamlit Community Cloud)

1. Push to GitHub (`.gitignore` keeps recordings, reports and secrets out).
2. share.streamlit.io → *New app* → repo, branch `main`, file `app.py`.
3. *Advanced settings → Secrets*: paste the contents of `secrets.toml.example` with real keys.

Every push to `main` redeploys. GitHub Actions runs `ruff` and `pytest` on each push; the APIs are
mocked in tests, so CI needs no keys and costs nothing.

## Limits of the free tiers

- **Upload size:** 10 minutes of 1080p video is ~740 MB. The app accepts up to 800 MB, but long
  meetings should be uploaded as audio (Zoom/Meet/Teams can export it, or use `--audio-only`):
  1 hour of audio is ~15 MB.
- **Rate limits:** both free tiers cap requests and audio per minute/day. Fine for a few meetings a
  day; the SDKs retry with backoff and the app shows a clear message when the quota is hit.
- **Privacy:** on Gemini's free tier Google may use submitted content to improve its products. For
  confidential meetings use a paid tier or swap `summarize.py` for a model on Groq.
- The summary is AI-generated: review it before sharing.

## Tests

```bash
ruff check . && pytest -v
```
