from types import SimpleNamespace

import pytest

from meeting_summarizer import summarize

SAMPLE = summarize.MeetingSummary(
    language="en",
    title="ACME monthly meeting",
    executive_summary="First paragraph.\n\nSecond paragraph.",
    topics=[summarize.Topic(title="Contoso partnership", description="Access to courses.", start="00:01:10")],
    decisions=["Announce the partnership"],
    action_items=[summarize.ActionItem(owner="Not specified", task="Create courses", due="Not specified")],
    risks=[],
    open_questions=["Date of the live session"],
)


def test_parse_uses_parsed_object_when_present():
    assert summarize.parse_response(SimpleNamespace(parsed=SAMPLE, text="ignored")) is SAMPLE


def test_parse_falls_back_to_json_text():
    resp = SimpleNamespace(parsed=None, text=SAMPLE.model_dump_json())
    assert summarize.parse_response(resp) == SAMPLE


def test_prompt_has_transcript_and_glossary_but_no_example_topics():
    prompt = summarize.build_prompt("[00:00:01] hello", ["ACME", "Contoso"])
    assert "[00:00:01] hello" in prompt
    assert "ACME, Contoso" in prompt
    assert "partnership" not in prompt.lower()  # regression: the prototype prompt leaked example topics


def test_summary_is_written_in_the_meeting_language():
    assert "SAME language spoken in the meeting" in summarize.SYSTEM_INSTRUCTION


class _NotFound(Exception):
    code = 404


class _Quota(Exception):
    code = 429


class FakeGemini:
    def __init__(self, outcomes):
        self.outcomes, self.tried = outcomes, []
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, model, contents, config):
        self.tried.append(model)
        outcome = self.outcomes[model]
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(parsed=outcome, text="")


class _Busy(Exception):
    code = 503


class _BadKey(Exception):
    code = 401


@pytest.mark.parametrize("error", [_NotFound(), _Quota(), _Busy()])
def test_retired_busy_or_out_of_quota_model_falls_back(error):
    client = FakeGemini({"first": error, "second": SAMPLE})
    assert summarize.generate_with_fallback(client, ["first", "second"], "p", None) == (SAMPLE, "second")
    assert client.tried == ["first", "second"]


def test_invalid_key_is_not_retried_on_other_models():
    client = FakeGemini({"a": _BadKey(), "b": SAMPLE})
    with pytest.raises(_BadKey):
        summarize.generate_with_fallback(client, ["a", "b"], "p", None)
    assert client.tried == ["a"]


def test_last_model_error_is_raised():
    client = FakeGemini({"a": _Busy(), "b": _Busy()})
    with pytest.raises(_Busy):
        summarize.generate_with_fallback(client, ["a", "b"], "p", None)


def test_model_chain_parsing():
    assert summarize.model_chain(" x , y,,") == ["x", "y"]
