"""Step 4 - render the summary as a Word document (in memory, no temp file)."""

from __future__ import annotations

from datetime import date
from io import BytesIO

from docx import Document
from docx.shared import Pt, RGBColor

from meeting_summarizer.summarize import ResumoReuniao
from meeting_summarizer.transcribe import Segment, hhmmss

_EMPTY = "Nenhum item identificado na reunião."
_GREY = RGBColor(0x66, 0x66, 0x66)


def _bullets(doc: Document, items: list[str]) -> None:
    if not items:
        doc.add_paragraph(_EMPTY).runs[0].italic = True
        return
    for item in items:
        doc.add_paragraph(item, style="List Bullet")


def build_docx(
    summary: ResumoReuniao,
    segments: list[Segment] | None = None,
    source_name: str = "",
    meeting_date: date | None = None,
) -> bytes:
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)

    doc.add_heading(summary.titulo, level=0)
    meta = doc.add_paragraph()
    meta_run = meta.add_run(
        f"Gerado em {(meeting_date or date.today()).strftime('%d/%m/%Y')}"
        + (f" · Fonte: {source_name}" if source_name else "")
        + " · Resumo automático, revise antes de compartilhar"
    )
    meta_run.font.size = Pt(9)
    meta_run.font.color.rgb = _GREY

    doc.add_heading("Resumo executivo", level=1)
    for paragraph in filter(None, (p.strip() for p in summary.resumo_executivo.split("\n\n"))):
        doc.add_paragraph(paragraph)

    doc.add_heading("Principais temas", level=1)
    if not summary.topicos:
        doc.add_paragraph(_EMPTY).runs[0].italic = True
    for topico in summary.topicos:
        p = doc.add_paragraph(style="List Number")
        p.add_run(topico.titulo).bold = True
        time_run = p.add_run(f"  ({topico.inicio})")
        time_run.font.color.rgb = _GREY
        doc.add_paragraph(topico.descricao).paragraph_format.left_indent = Pt(18)

    doc.add_heading("Decisões tomadas", level=1)
    _bullets(doc, summary.decisoes)

    doc.add_heading("Próximas ações", level=1)
    if summary.proximas_acoes:
        table = doc.add_table(rows=1, cols=3)
        table.style = "Light Grid Accent 1"
        for cell, label in zip(table.rows[0].cells, ("Responsável", "Ação", "Prazo"), strict=True):
            cell.text = label
        for acao in summary.proximas_acoes:
            row = table.add_row().cells
            row[0].text, row[1].text, row[2].text = acao.responsavel, acao.acao, acao.prazo
    else:
        doc.add_paragraph(_EMPTY).runs[0].italic = True

    doc.add_heading("Riscos e pontos de atenção", level=1)
    _bullets(doc, summary.riscos)

    doc.add_heading("Pendências", level=1)
    _bullets(doc, summary.pendencias)

    if segments:
        doc.add_page_break()
        doc.add_heading("Anexo: transcrição", level=1)
        for seg in segments:
            p = doc.add_paragraph()
            ts = p.add_run(f"[{hhmmss(seg.start)}] ")
            ts.font.color.rgb = _GREY
            ts.font.size = Pt(9)
            p.add_run(seg.text).font.size = Pt(10)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
