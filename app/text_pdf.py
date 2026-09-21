"""Build a simple, valid PDF from ingested text using the bundled pypdf.

Sentinel datasets are ingested as text chunks (OpenAlex records, HTML pages,
CSV/JSON rows, repository files). When no real .pdf artifact was stored, the
Download button still needs to deliver a .pdf — so the ingested text is
typeset into a minimal multi-page PDF with pypdf's PdfWriter.
"""
from __future__ import annotations

import io
import textwrap

from fastapi import Response
from pypdf import PdfWriter
from pypdf.generic import (
    DictionaryObject,
    NameObject,
    StreamObject,
)

# Conservative Helvetica metrics so lines never overflow the page.
_CHAR_WIDTH_UNITS = 554  # average glyph width at 1000 units/em
_PAGE_WIDTH_PT = 595     # A4
_PAGE_HEIGHT_PT = 842
_MARGIN_PT = 48
_FONT_SIZE_PT = 10.5
_LINE_HEIGHT_PT = _FONT_SIZE_PT * 1.45

_USABLE_WIDTH_PT = _PAGE_WIDTH_PT - 2 * _MARGIN_PT
_CHARS_PER_LINE = max(24, int((_USABLE_WIDTH_PT * 1000) / (_CHAR_WIDTH_UNITS * _FONT_SIZE_PT)))
_LINES_PER_PAGE = max(8, int((_PAGE_HEIGHT_PT - 2 * _MARGIN_PT) / _LINE_HEIGHT_PT))


def _escape_pdf_text(line: str) -> str:
    """Escape for a PDF literal string and force Latin-1 (Helvetica's range)."""
    safe = str(line).replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return safe.encode("latin-1", errors="replace").decode("latin-1")


def _wrap_text(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in str(text or "").replace("\r\n", "\n").split("\n"):
        if not raw_line.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(raw_line, width=_CHARS_PER_LINE) or [""])
    return lines


def build_pdf_bytes(text: str, title: str = "SMi Sentinel Dataset") -> bytes:
    title = str(title or "SMi Sentinel Dataset").strip()[:110] or "SMi Sentinel Dataset"
    header_lines = [title, "=" * min(72, max(8, len(title))), ""]

    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )
    )  # IndirectObject referencing the font dictionary

    body_lines = _wrap_text(text)
    pages: list[list[str]] = []
    current: list[str] = []
    page_capacity = _LINES_PER_PAGE - len(header_lines)
    for line in body_lines:
        current.append(line)
        if len(current) >= page_capacity:
            pages.append(current)
            current = []
    if current or not pages:
        pages.append(current)

    for page_lines in pages:
        stream = io.StringIO()
        y = _PAGE_HEIGHT_PT - _MARGIN_PT
        for line in [*header_lines, *page_lines]:
            safe = _escape_pdf_text(line)
            stream.write(f"BT /F1 {_FONT_SIZE_PT} Tf {_MARGIN_PT} {y:.1f} Td ({safe}) Tj ET\n")
            y -= _LINE_HEIGHT_PT
        content = stream.getvalue().encode("latin-1", errors="replace")

        page = writer.add_blank_page(width=_PAGE_WIDTH_PT, height=_PAGE_HEIGHT_PT)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        content_stream = StreamObject()
        content_stream.set_data(content)
        page[NameObject("/Contents")] = writer._add_object(content_stream)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def text_to_pdf_response(text: str, filename: str = "smi-dataset.pdf", title: str = "SMi Sentinel Dataset"):
    return Response(
        content=build_pdf_bytes(text, title=title),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
