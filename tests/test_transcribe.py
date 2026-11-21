from types import SimpleNamespace

from meeting_summarizer import transcribe


class FakeGroq:
    """Mimics client.audio.transcriptions.create and records the calls."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._create))

    def _create(self, file, **kwargs):
        self.calls.append((file[0], kwargs))
        return self.responses[file[0]]


def _parts(tmp_path, n):
    paths = []
    for i in range(n):
        p = tmp_path / f"part_{i:03d}.mp3"
        p.write_bytes(b"fake")
        paths.append(p)
    return paths


def test_offsets_order_and_silence_filter(tmp_path):
    client = FakeGroq({
        "part_000.mp3": {"segments": [{"start": 0.0, "end": 2.0, "text": " Olá ACME ", "no_speech_prob": 0.1}]},
        "part_001.mp3": {"segments": [
            {"start": 1.0, "end": 3.0, "text": "segunda parte", "no_speech_prob": 0.0},
            {"start": 5.0, "end": 6.0, "text": "Legendas Amara.org", "no_speech_prob": 0.95},
        ]},
    })
    segs = transcribe.transcribe_parts(client, _parts(tmp_path, 2), segment_seconds=900, glossary=["ACME"])

    assert segs == [
        transcribe.Segment(0.0, 2.0, "Olá ACME"),
        transcribe.Segment(901.0, 903.0, "segunda parte"),
    ]
    _, kwargs = client.calls[0]
    assert kwargs["language"] == "pt" and kwargs["response_format"] == "verbose_json"
    assert "ACME" in kwargs["prompt"]


def test_falls_back_to_plain_text(tmp_path):
    client = FakeGroq({"part_000.mp3": SimpleNamespace(text="só texto", segments=None)})
    segs = transcribe.transcribe_parts(client, _parts(tmp_path, 1), segment_seconds=900)
    assert segs == [transcribe.Segment(0.0, 0.0, "só texto")]


def test_prompt_is_capped():
    assert len(transcribe.build_whisper_prompt(["termo"] * 500)) <= 600


def test_format_transcript():
    text = transcribe.format_transcript([transcribe.Segment(3725, 3726, "oi")])
    assert text == "[01:02:05] oi"

