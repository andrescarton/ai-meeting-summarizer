from io import BytesIO

from docx import Document

from meeting_summarizer.docx_report import build_docx
from meeting_summarizer.transcribe import Segment
from tests.test_summarize import SAMPLE


def _text(docx_bytes):
    doc = Document(BytesIO(docx_bytes))
    body = "\n".join(p.text for p in doc.paragraphs)
    cells = "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
    return body, cells


def test_english_docx_contains_all_sections():
    body, cells = _text(build_docx(SAMPLE, [Segment(65, 70, "hello")], "meeting.mp4"))
    for heading in ["Executive summary", "Main topics", "Decisions", "Action items",
                    "Risks and points of attention", "Open questions", "Appendix: transcript"]:
        assert heading in body
    assert "Contoso partnership" in body and "[00:01:05] hello" in body
    assert "No items identified" in body  # empty risks list
    assert "Create courses" in cells and "Owner" in cells


def test_headings_follow_meeting_language():
    body, cells = _text(build_docx(SAMPLE.model_copy(update={"language": "pt"}), None))
    assert "Resumo executivo" in body and "Pendências" in body and "Responsável" in cells
    assert "Anexo: transcrição" not in body  # no transcript passed


def test_unknown_language_falls_back_to_english_headings():
    body, _ = _text(build_docx(SAMPLE.model_copy(update={"language": "de"}), None))
    assert "Executive summary" in body
