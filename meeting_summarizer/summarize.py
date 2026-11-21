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
DEFAULT_MODEL = "gemini-3.8-flash,gemini-3.7-flash,gemini-3.5-flash"


class Topico(BaseModel):
    titulo: str = Field(description="Nome curto do tema")
    descricao: str = Field(description="2 a 4 frases sobre o que foi dito sobre o tema")
    inicio: str = Field(description="Timestamp HH:MM:SS em que o tema começou a ser discutido")


class Acao(BaseModel):
    responsavel: str = Field(description="Quem vai executar, ou 'Não definido'")
    acao: str
    prazo: str = Field(description="Prazo mencionado, ou 'Não definido'")


class ResumoReuniao(BaseModel):
    titulo: str = Field(description="Título descritivo da reunião")
    resumo_executivo: str = Field(description="2 a 3 parágrafos separados por linha em branco")
    topicos: list[Topico] = Field(description="Principais temas, em ordem cronológica")
    decisoes: list[str]
    proximas_acoes: list[Acao]
    riscos: list[str] = Field(description="Riscos e pontos de atenção")
    pendencias: list[str] = Field(description="Perguntas ou assuntos que ficaram em aberto")


SYSTEM_INSTRUCTION = (
    "Você é um analista de reuniões experiente. Trabalhe SOMENTE com o que está explícito "
    "na transcrição. Não invente fatos, decisões, responsáveis, prazos ou riscos: se algo não "
    "foi dito, use uma lista vazia ou 'Não definido'. Agrupe falas sobre o mesmo assunto em um "
    "único tópico, ignore conversa de abertura e logística sem conteúdo. Escreva em português."
)


def build_prompt(transcript: str, glossary: list[str]) -> str:
    # Note: no example topics here. The prototype's prompt listed example topics,
    # which made the model "find" those topics in every meeting.
    glossary_line = f"Grafia correta de nomes próprios: {', '.join(glossary)}.\n" if glossary else ""
    return (
        "Analise a transcrição de reunião abaixo (cada linha começa com o timestamp).\n"
        "A transcrição é automática e pode ter erros de reconhecimento de nomes; corrija-os "
        "quando o contexto deixar claro.\n"
        f"{glossary_line}\n"
        f"<transcricao>\n{transcript}\n</transcricao>"
    )


def parse_response(resp: Any) -> ResumoReuniao:
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, ResumoReuniao):
        return parsed
    return ResumoReuniao.model_validate_json(resp.text)


def summarize(
    transcript: str, api_key: str, model: str = DEFAULT_MODEL, glossary: list[str] | None = None
) -> ResumoReuniao:
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
        response_schema=ResumoReuniao,
        temperature=0.2,  # low = faithful to the transcript, little "creativity"
    )
    return generate_with_fallback(client, model_chain(model), build_prompt(transcript, glossary or []), config)


def model_chain(model: str) -> list[str]:
    return [m.strip() for m in model.split(",") if m.strip()]


def generate_with_fallback(client: Any, models: list[str], prompt: str, config: Any) -> ResumoReuniao:
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
    raise ValueError("Nenhum modelo Gemini configurado.")
