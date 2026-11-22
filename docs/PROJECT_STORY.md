# The story behind the AI Meeting Summarizer

A plain-language walk through what I built, the problems I hit and why I made each choice.

## The request

I volunteer at a non-profit that holds a monthly meeting with its volunteers. The meetings are recorded, but nobody has time to watch an hour of video to find out what was decided. They asked me for something simple: give it the recording, get the minutes back. And it had to be free, because a non-profit can't take on another monthly bill.

## First attempt: everything on my own GPU

My first version was a Google Colab notebook. It used Whisper to turn speech into text and Llama 3.1 8B, an open model, to write the summary, both running on Colab's free GPU.

It worked, but:

- **It was slow.** A 10-minute meeting took 18.5 minutes. Loading the models alone took two minutes.
- **It couldn't go online.** Free hosting like Streamlit Community Cloud has no GPU and little memory, so the two models would never fit.
- **The summaries were vague.** An 8B model can only read a short piece of text at a time, so I cut the transcript into 2-minute chunks, summarised each one and merged the results. Every chunk lost the context of the rest, and the final topics came out as "Questions" and "Activities".
- **The prompt was cheating.** To show the model the format I wanted, I had written example topics taken from this very meeting. On any other meeting it would have "found" those topics anyway.

## The idea: keep the app light, rent the heavy work for free

The app itself only needs to do light jobs: pull the audio out of the video and build a Word file. The heavy work, transcribing and summarising, can go to services that have a free tier:

- **Groq** runs Whisper large-v3, a bigger and more accurate Whisper than the one I used in Colab, on hardware built for it. The 10-minute meeting transcribes in about 5 seconds.
- **Google Gemini** can read about a million tokens at once. A one-hour meeting is around 20,000, so the whole transcript fits in one request: no chunks, no merging, and nothing lost between pieces.

## Step by step

**1. Make the file small.** Whisper only uses mono audio at 16 kHz, so sending anything richer just slows the upload. ffmpeg throws away the video and compresses the speech: the 738 MB sample video becomes a 2.4 MB MP3. Long meetings are split into 15-minute parts, which keeps every part under Groq's 25 MB limit and lets them be transcribed at the same time.

**2. Transcribe with a glossary.** Whisper kept writing the organisation's name as a different word that sounded alike. Whisper accepts a short "prompt" that it treats as text said just before the audio, so passing it a list of names and acronyms fixes their spelling. The same list goes to Gemini. I also drop the bits Whisper itself marks as probably silence, which is where it tends to invent phrases.

**3. Ask for structure, not prose.** Instead of asking for text and then picking it apart with regular expressions, I describe the answer as a Pydantic schema (title, executive summary, topics with timestamps, decisions, action items with owner and deadline, risks, open questions) and Gemini returns JSON that fits it. The summary is written in whatever language the meeting was in.

**4. Build the document.** python-docx writes the Word file in memory, so nothing is left on the server's disk.

## Things I learned along the way

**The prompt mattered more than the model.** My schema said "2 to 4 sentences" per topic, and the model did exactly that, so the descriptions were thin. When I asked instead for who presented each topic and every name, number and date mentioned, the same model wrote about 40% more, and more useful, text. The descriptions in a schema are instructions too.

**Measure, then look.** I compared models by counting topics and words, and on those numbers the faster model looked as good. Reading the actual summaries showed it wasn't. Numbers help, but for writing you still have to read the output.

**Free tiers have moods.** The newest Gemini model sometimes answered "high demand, try later" and sometimes queued for minutes. Google also retires old models: one I planned to use already returned "not found" for new accounts. So the app keeps a list of models and moves to the next one when a model is retired, out of quota or overloaded. If the key is wrong it stops straight away, because every model would fail.

**Streamlit reruns everything on every click.** Even pressing "download" runs the whole script again. Without care, that would call the APIs again and burn the free quota, so the result is kept in the session and only recomputed for a new file or new settings.

**Secrets don't go in code.** The API keys live in Streamlit's secrets, never in the repository, and the old notebooks stay out of it.

## Where it ended up

From 18.5 minutes on a GPU to a few seconds of transcription plus the summary, at no cost, online for the volunteers to use. The sidebar lets them pick *Best quality* (richer text, can take a few minutes) or *Fast* (about 30 seconds).
