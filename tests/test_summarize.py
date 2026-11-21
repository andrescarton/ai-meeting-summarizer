from types import SimpleNamespace

from meeting_summarizer import summarize

SAMPLE = summarize.ResumoReuniao(
    titulo="Reunião mensal ACME",
    resumo_executivo="Primeiro parágrafo.\n\nSegundo parágrafo.",
    topicos=[summarize.Topico(titulo="Parceria Contoso", descricao="Acesso a cursos.", inicio="00:01:10")],
    decisoes=["Divulgar a parceria"],
    proximas_acoes=[summarize.Acao(responsavel="Não definido", acao="Criar cursos", prazo="Não definido")],
    riscos=[],
    pendencias=["Data da live"],
)


def test_parse_uses_parsed_object_when_present():
    assert summarize.parse_response(SimpleNamespace(parsed=SAMPLE, text="ignored")) is SAMPLE


def test_parse_falls_back_to_json_text():
    resp = SimpleNamespace(parsed=None, text=SAMPLE.model_dump_json())
    assert summarize.parse_response(resp) == SAMPLE


def test_prompt_has_transcript_and_glossary_but_no_hardcoded_topics():
    prompt = summarize.build_prompt("[00:00:01] olá", ["ACME", "Contoso"])
    assert "[00:00:01] olá" in prompt
    assert "ACME, Contoso" in prompt
    assert "Parceria" not in prompt  # regression: the prototype prompt leaked example topics


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


def test_retired_model_falls_back_to_next():
    client = FakeGemini({"old": _NotFound(), "new": SAMPLE})
    assert summarize.generate_with_fallback(client, ["old", "new"], "p", None) is SAMPLE
    assert client.tried == ["old", "new"]


def test_quota_error_is_not_retried_on_other_models():
    client = FakeGemini({"a": _Quota(), "b": SAMPLE})
    try:
        summarize.generate_with_fallback(client, ["a", "b"], "p", None)
        raise AssertionError("expected quota error")
    except _Quota:
        pass
    assert client.tried == ["a"]


def test_model_chain_parsing():
    assert summarize.model_chain(" x , y,,") == ["x", "y"]
