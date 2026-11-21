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


def test_docx_contains_all_sections():
    body, cells = _text(build_docx(SAMPLE, [Segment(65, 70, "fala")], "reuniao.mp4"))
    for heading in ["Resumo executivo", "Principais temas", "Decisões tomadas", "Próximas ações",
                    "Riscos e pontos de atenção", "Pendências", "Anexo: transcrição"]:
        assert heading in body
    assert "Parceria Contoso" in body and "[00:01:05] fala" in body
    assert "Nenhum item identificado" in body  # empty riscos list
    assert "Criar cursos" in cells


def test_docx_without_transcript():
    body, _ = _text(build_docx(SAMPLE, None))
    assert "Anexo: transcrição" not in body
