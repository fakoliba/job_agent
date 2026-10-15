from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.shared import Pt
from fpdf import FPDF

from modules.schemas import StructuredResume


def _pdf_safe(text: str) -> str:
    return text.encode("ascii", errors="replace").decode("ascii")


def _wrap_long_tokens(text: str, max_chunk: int = 72) -> str:
    """Insert soft breaks so fpdf can wrap lines with very long tokens (URLs, etc.)."""
    parts: list[str] = []
    for word in text.split():
        if len(word) > max_chunk:
            parts.append("\n".join(word[i : i + max_chunk] for i in range(0, len(word), max_chunk)))
        else:
            parts.append(word)
    return " ".join(parts)


def _add_heading(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(12)


def _add_bullets(doc: Document, items: list[str]) -> None:
    for line in items:
        if line.strip():
            doc.add_paragraph(line.strip(), style="List Bullet")


def structured_resume_to_docx(resume: StructuredResume, document_title: str) -> bytes:
    doc = Document()
    doc.add_heading(document_title, 0)
    if resume.summary.strip():
        _add_heading(doc, "Summary")
        doc.add_paragraph(resume.summary.strip())
    if resume.experience:
        _add_heading(doc, "Experience")
        _add_bullets(doc, resume.experience)
    if resume.skills:
        _add_heading(doc, "Skills")
        doc.add_paragraph(", ".join(s.strip() for s in resume.skills if s.strip()))
    if resume.impact:
        _add_heading(doc, "Impact")
        _add_bullets(doc, resume.impact)
    if resume.leadership:
        _add_heading(doc, "Leadership")
        _add_bullets(doc, resume.leadership)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


class _ResumePDF(FPDF):
    def __init__(self) -> None:
        super().__init__()
        self.set_auto_page_break(auto=True, margin=15)

    def _usable_width(self) -> float:
        return self.w - self.r_margin - self.l_margin

    def _write_block(self, font_size: int, style: str, height: float, text: str) -> None:
        self.set_x(self.l_margin)
        self.set_font("Helvetica", style, font_size)
        safe = _wrap_long_tokens(_pdf_safe(text))
        self.multi_cell(self._usable_width(), height, safe)

    def section(self, title: str, body_lines: list[str]) -> None:
        self._write_block(12, "B", 8.0, title)
        self.ln(2)
        self.set_font("Helvetica", "", 10)
        for line in body_lines:
            text = line.strip()
            if not text:
                continue
            self._write_block(10, "", 5.0, text)
        self.ln(4)


def structured_resume_to_pdf(resume: StructuredResume, document_title: str) -> bytes:
    pdf = _ResumePDF()
    pdf.add_page()
    pdf._write_block(16, "B", 10.0, document_title)
    pdf.ln(4)
    if resume.summary.strip():
        pdf.section("Summary", [resume.summary.strip()])
    if resume.experience:
        pdf.section("Experience", resume.experience)
    if resume.skills:
        pdf.section("Skills", [", ".join(s for s in resume.skills if s.strip())])
    if resume.impact:
        pdf.section("Impact", resume.impact)
    if resume.leadership:
        pdf.section("Leadership", resume.leadership)
    out = pdf.output()
    return bytes(out) if isinstance(out, (bytearray, memoryview)) else out
