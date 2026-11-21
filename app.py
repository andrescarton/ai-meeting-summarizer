"""Streamlit front-end: upload a meeting recording, get a summary .docx."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import streamlit as st

from meeting_summarizer import pipeline, summarize, transcribe
from meeting_summarizer.docx_report import build_docx

st.set_page_config(page_title="Resumo de reuniões", page_icon="📝", layout="centered")


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
        return "Limite gratuito da API atingido. Aguarde alguns minutos e tente de novo."
    if name in {"AuthenticationError", "PermissionDeniedError"} or code in {401, 403}:
        return "Chave de API inválida. Confira GROQ_API_KEY e GEMINI_API_KEY nos Secrets."
    if code == 413 or "too large" in str(exc).lower():
        return "Parte de áudio grande demais para o plano gratuito do Groq."
    return f"Erro inesperado ({name}): {exc}"


GROQ_KEY = get_setting("GROQ_API_KEY")
GEMINI_KEY = get_setting("GEMINI_API_KEY")

st.title("📝 Resumo de reuniões")
st.caption("Envie a gravação da reunião e receba um documento com resumo executivo, temas, decisões e próximas ações.")

with st.sidebar:
    st.header("Configurações")
    glossary_text = st.text_area(
        "Glossário (um termo por linha)",
        "\n".join(pipeline.DEFAULT_GLOSSARY),
        help=(
            "Nomes próprios e siglas da reunião. Ajuda o Whisper e o Gemini a escrever certo "
            "(ex.: siglas da organização, nomes de parceiros e de pessoas)."
        ),
        height=200,
    )
    include_transcript = st.checkbox("Anexar transcrição ao documento", value=True)
    st.divider()
    st.caption(
        "Dica: vídeos em alta resolução são enormes (10 min em 1080p ≈ 700 MB). "
        "Envie só o áudio (.mp3/.m4a) sempre que puder: o upload fica muito mais rápido."
    )

if not (GROQ_KEY and GEMINI_KEY):
    st.warning(
        "Configure GROQ_API_KEY e GEMINI_API_KEY em `.streamlit/secrets.toml` (local) "
        "ou nos Secrets do Streamlit Cloud."
    )
    st.stop()

uploaded = st.file_uploader(
    "Gravação da reunião",
    type=["mp3", "m4a", "wav", "ogg", "webm", "mp4", "mov", "mkv"],
)
glossary = [t.strip() for t in glossary_text.splitlines() if t.strip()]

# Streamlit re-runs this whole script on EVERY interaction (even clicking
# "download"). Keeping the result in session_state, keyed by the upload, means
# the APIs are called once per file instead of once per click.
run_key = (uploaded.file_id, tuple(glossary)) if uploaded else None

if uploaded and st.button("Gerar resumo", type="primary", use_container_width=True):
    with st.status("Processando a reunião...", expanded=True) as status:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                # ffmpeg needs a real file path; stream the upload to disk.
                input_path = Path(tmp) / Path(uploaded.name).name
                input_path.write_bytes(uploaded.getbuffer())
                result = pipeline.run(
                    input_path,
                    groq_api_key=GROQ_KEY,
                    gemini_api_key=GEMINI_KEY,
                    glossary=glossary,
                    whisper_model=get_setting("WHISPER_MODEL", transcribe.DEFAULT_MODEL),
                    gemini_model=get_setting("GEMINI_MODEL", summarize.DEFAULT_MODEL),
                    progress=st.write,
                )
            st.session_state["result"] = result
            st.session_state["run_key"] = run_key
            status.update(label=f"Pronto em {result.timings['total_s']:.0f} s", state="complete", expanded=False)
        except Exception as exc:  # show a readable message instead of a stack trace
            status.update(label="Falhou", state="error")
            st.error(friendly_error(exc))

result: pipeline.PipelineResult | None = st.session_state.get("result")
if result is None or st.session_state.get("run_key") != run_key:
    st.stop()

summary = result.summary
docx_bytes = build_docx(summary, result.segments if include_transcript else None, uploaded.name)
st.download_button(
    "⬇️ Baixar documento (.docx)",
    data=docx_bytes,
    file_name=f"{Path(uploaded.name).stem}_resumo.docx",
    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    type="primary",
    use_container_width=True,
)

tab_summary, tab_actions, tab_transcript, tab_timing = st.tabs(["Resumo", "Decisões e ações", "Transcrição", "Tempos"])

with tab_summary:
    st.subheader(summary.titulo)
    st.markdown(summary.resumo_executivo)
    st.markdown("#### Principais temas")
    for topico in summary.topicos:
        with st.expander(f"{topico.titulo} · {topico.inicio}"):
            st.write(topico.descricao)

with tab_actions:
    st.markdown("#### Decisões")
    st.markdown("\n".join(f"- {d}" for d in summary.decisoes) or "_Nenhuma._")
    st.markdown("#### Próximas ações")
    if summary.proximas_acoes:
        st.dataframe([a.model_dump() for a in summary.proximas_acoes], hide_index=True, use_container_width=True)
    else:
        st.markdown("_Nenhuma._")
    st.markdown("#### Riscos e pontos de atenção")
    st.markdown("\n".join(f"- {r}" for r in summary.riscos) or "_Nenhum._")
    st.markdown("#### Pendências")
    st.markdown("\n".join(f"- {p}" for p in summary.pendencias) or "_Nenhuma._")

with tab_transcript:
    st.text_area("Transcrição", result.transcript, height=400, label_visibility="collapsed")

with tab_timing:
    st.dataframe(
        [{"etapa": k, "segundos": round(v, 1)} for k, v in result.timings.items()],
        hide_index=True,
        use_container_width=True,
    )
