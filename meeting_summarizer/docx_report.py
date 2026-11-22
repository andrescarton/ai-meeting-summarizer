"""Step 4 - render the summary as a Word document (in memory, no temp file)."""

from __future__ import annotations

from datetime import date
from io import BytesIO

from docx import Document
from docx.shared import Pt, RGBColor

from meeting_summarizer.summarize import MeetingSummary
from meeting_summarizer.transcribe import Segment, hhmmss

# Fixed section headings per language (ISO 639-1). The summary text itself is
# written by Gemini in the meeting's language; unknown languages fall back to English.
LABELS: dict[str, dict[str, str]] = {
    "en": {
        "generated": "Generated on", "date_fmt": "%Y-%m-%d", "source": "Source",
        "disclaimer": "AI-generated summary, review before sharing",
        "summary": "Executive summary", "topics": "Main topics", "decisions": "Decisions",
        "actions": "Action items", "owner": "Owner", "task": "Task", "due": "Due",
        "risks": "Risks and points of attention", "open": "Open questions",
        "transcript": "Appendix: transcript", "empty": "No items identified in the meeting.",
    },
    "pt": {
        "generated": "Gerado em", "date_fmt": "%d/%m/%Y", "source": "Fonte",
        "disclaimer": "Resumo automático, revise antes de compartilhar",
        "summary": "Resumo executivo", "topics": "Principais temas", "decisions": "Decisões tomadas",
        "actions": "Próximas ações", "owner": "Responsável", "task": "Ação", "due": "Prazo",
        "risks": "Riscos e pontos de atenção", "open": "Pendências",
        "transcript": "Anexo: transcrição", "empty": "Nenhum item identificado na reunião.",
    },
}
_GREY = RGBColor(0x66, 0x66, 0x66)


def _empty(doc: Document, text: str) -> None:
    doc.add_paragraph(text).runs[0].italic = True


def _bullets(doc: Document, items: list[str], empty_text: str) -> None:
    if not items:
        _empty(doc, empty_text)
    for item in items:
        doc.add_paragraph(item, style="List Bullet")


def build_docx(
    summary: MeetingSummary,
    segments: list[Segment] | None = None,
    source_name: str = "",
    meeting_date: date | None = None,
) -> bytes:
    lb = LABELS.get(summary.language.lower()[:2], LABELS["en"])
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)

    doc.add_heading(summary.title, level=0)
    meta_run = doc.add_paragraph().add_run(
        f"{lb['generated']} {(meeting_date or date.today()).strftime(lb['date_fmt'])}"
        + (f" · {lb['source']}: {source_name}" if source_name else "")
        + f" · {lb['disclaimer']}"
    )
    meta_run.font.size = Pt(9)
    meta_run.font.color.rgb = _GREY

    doc.add_heading(lb["summary"], level=1)
    for paragraph in filter(None, (p.strip() for p in summary.executive_summary.split("\n\n"))):
        doc.add_paragraph(paragraph)

    doc.add_heading(lb["topics"], level=1)
    if not summary.topics:
        _empty(doc, lb["empty"])
    for topic in summary.topics:
        p = doc.add_paragraph(style="List Number")
        p.add_run(topic.title).bold = True
        p.add_run(f"  ({topic.start})").font.color.rgb = _GREY
        doc.add_paragraph(topic.description).paragraph_format.left_indent = Pt(18)

    doc.add_heading(lb["decisions"], level=1)
    _bullets(doc, summary.decisions, lb["empty"])

    doc.add_heading(lb["actions"], level=1)
    if summary.action_items:
        table = doc.add_table(rows=1, cols=3)
        table.style = "Light Grid Accent 1"
        for cell, label in zip(table.rows[0].cells, (lb["owner"], lb["task"], lb["due"]), strict=True):
            cell.text = label
        for item in summary.action_items:
            row = table.add_row().cells
            row[0].text, row[1].text, row[2].text = item.owner, item.task, item.due
    else:
        _empty(doc, lb["empty"])

    doc.add_heading(lb["risks"], level=1)
    _bullets(doc, summary.risks, lb["empty"])

    doc.add_heading(lb["open"], level=1)
    _bullets(doc, summary.open_questions, lb["empty"])

    if segments:
        doc.add_page_break()
        doc.add_heading(lb["transcript"], level=1)
        for seg in segments:
            p = doc.add_paragraph()
            ts = p.add_run(f"[{hhmmss(seg.start)}] ")
            ts.font.color.rgb = _GREY
            ts.font.size = Pt(9)
            p.add_run(seg.text).font.size = Pt(10)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
