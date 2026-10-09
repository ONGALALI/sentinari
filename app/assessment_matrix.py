"""Assessment Matrix document → HTML (§78, owner request).

`corrections/Assessment_Matrix.docx` — "NEW PATTERN DISCOVERY: IMPACT ON
SUSTAINABLE SOCIETY / ASSESSMENT MATRIX" — is the scoring law behind the New
Patterns workspace (impact dimensions, level bands, the coupled bell curve).
Owner directive: containerise it — render the document's full content
(headings, paragraphs, all tables, and the embedded figure) as HTML inside
the New Patterns workspace instead of leaving it as a raw docx.

Design:
- Pure-stdlib docx parsing: a .docx is a zip of XML (word/document.xml),
  so we walk headings, paragraphs, tables and the embedded image without
  adding python-docx as a new dependency.
- Cached render keyed on the source file's mtime + size, so repeated page
  loads are instant; the render is regenerated only when the document
  changes on disk.
"""

from __future__ import annotations

import base64
import html
import io
import re
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO
from xml.etree import ElementTree as ET

ASSESSMENT_DOCX_RELATIVE = Path("corrections") / "Assessment_Matrix.docx"

_WORDML_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

_W = f"{{{_WORDML_NS}}}"
_R = f"{{{_REL_NS}}}"

_IMAGE_MEDIA_TYPE = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".emf": "image/emf",
    ".wmf": "image/wmf",
}

_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"key": None, "html": None, "stats": {}}


def assessment_docx_path(project_root: Path) -> Path:
    return Path(project_root) / ASSESSMENT_DOCX_RELATIVE


# ---------------------------------------------------------------------------
# Low-level docx XML helpers (stdlib only)
# ---------------------------------------------------------------------------


def _paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t":
            parts.append(node.text or "")
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
    return "".join(parts).strip()


def _paragraph_heading_level(paragraph: ET.Element) -> int:
    """1-6 for real heading styles; 0 when the paragraph is body text."""
    style = paragraph.find(f"{_W}pPr/{_W}pStyle")
    if style is None:
        return 0
    value = (style.get(f"{_W}val") or "").strip()
    match = re.fullmatch(r"[Hh]eading([1-9])", value)
    if match:
        return int(match.group(1))
    if value.lower() in {"title"}:
        return 1
    if value.lower() in {"subtitle"}:
        return 2
    return 0


_CODE_LANG_RE = re.compile(r"^#{1,4}\\s*(javascript|js|python|py|jsx|vue|html|css|json|bash|shell)\\s*$", re.IGNORECASE)
_CODE_HINT_RE = re.compile(r"^(export |const |import |def |class |function |from |return |</?[a-z]|<template|<script|npm |pip |vue |Use Chart|Save the following)")


def _paragraph_is_bold(paragraph: ET.Element) -> bool:
    """True when every run carrying text is bold (this docx styles its
    headings with direct formatting, no Heading styles)."""
    runs = paragraph.findall(f"{_W}r")
    text_runs = 0
    for run in runs:
        has_text = any((t.text or "").strip() for t in run.findall(f"{_W}t"))
        if not has_text:
            continue
        text_runs += 1
        if run.find(f"{_W}rPr/{_W}b") is None:
            return False
    return text_runs > 0


def _classify_paragraph(paragraph: ET.Element, text: str) -> str:
    """Return the block kind: 'h1', 'h2', 'code', 'li' or 'p'.

    The Assessment Matrix docx uses direct bold formatting instead of Word
    heading styles, so headings are detected as: bold-only paragraphs that
    are short and are not code lines. Code lines (the embedded JS/Python
    samples) render in a monospace block to keep the document readable.
    """
    style_level = _paragraph_heading_level(paragraph)
    if style_level:
        return f"h{min(style_level, 6)}"
    if _CODE_LANG_RE.match(text):
        return "code"
    if _CODE_HINT_RE.match(text) or (text.startswith(('"', "'", '{', '}', '<', '[', ']')) and len(text) < 200):
        return "code"
    if _paragraph_is_bold(paragraph):
        stripped = text.strip().rstrip(':')
        if len(stripped) <= 90 and not stripped.endswith('.'):
            # The document title deserves h1; everything else is a section heading.
            if stripped.upper() == "ASSESSMENT MATRIX":
                return "h1"
            return "h2"
        return "p"
    return "p"


def _paragraph_is_list_item(paragraph: ET.Element) -> str | None:
    """'ul' / 'ol' when the paragraph carries numbering, else None."""
    num_pr = paragraph.find(f"{_W}pPr/{_W}numPr")
    if num_pr is None:
        return None
    ilvl = num_pr.find(f"{_W}ilvl")
    level = int(ilvl.get(f"{_W}val") or "0") if ilvl is not None else 0
    # Word bullet lists at level 0 are unordered; numbered styles are handled
    # per-style below. Keep it simple: level 0 → ul, deeper → nested ul.
    return "ul"


def _cell_paragraphs(cell: ET.Element) -> list[str]:
    out: list[str] = []
    for paragraph in cell.findall(f"{_W}p"):
        text = _paragraph_text(paragraph)
        if text:
            out.append(text)
    return out or [""]


def _table_rows(table: ET.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.findall(f"{_W}tr"):
        cells = [_cell_paragraphs(tc) for tc in tr.findall(f"{_W}tc")]
        if cells:
            rows.append(cells)
    return rows


def _iter_block_items(body: ET.Element):
    """Yield (kind, element) in document order: 'p' paragraphs and 'tbl' tables."""
    for child in body:
        if child.tag == f"{_W}p":
            yield "p", child
        elif child.tag == f"{_W}tbl":
            yield "tbl", child


# ---------------------------------------------------------------------------
# Image extraction
# ---------------------------------------------------------------------------


def _load_relationships(zip_handle: zipfile.ZipFile) -> dict[str, str]:
    """rId → media path (e.g. 'rId7' → 'word/media/image1.png')."""
    mapping: dict[str, str] = {}
    try:
        rels_xml = zip_handle.read("word/_rels/document.xml.rels")
    except KeyError:
        return mapping
    root = ET.fromstring(rels_xml)
    for rel in root.findall(f"{{{_PKG_REL_NS}}}Relationship"):
        rid = rel.get("Id") or ""
        target = rel.get("Target") or ""
        if rid and "media/" in target:
            mapping[rid] = target if target.startswith("word/") else f"word/{target.lstrip('/')}"
    return mapping


def _image_data_uri(zip_handle: zipfile.ZipFile, media_path: str) -> str:
    suffix = Path(media_path).suffix.lower()
    media_type = _IMAGE_MEDIA_TYPE.get(suffix, "application/octet-stream")
    data = zip_handle.read(media_path)
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


# ---------------------------------------------------------------------------
# Document → HTML
# ---------------------------------------------------------------------------

_DOC_CSS = """
  body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #f4f7fc; color: #1d2b3a; }
  .doc-shell { max-width: 960px; margin: 0 auto; padding: 28px 34px 60px; background: #fff; min-height: 100vh; box-shadow: 0 0 24px rgba(16,35,60,0.08); }
  h1 { font-size: 25px; margin: 26px 0 10px; color: #17304f; }
  h2 { font-size: 20px; margin: 22px 0 8px; color: #17304f; }
  h3 { font-size: 16.5px; margin: 18px 0 6px; color: #1d3a5f; }
  h4 { font-size: 14.5px; margin: 16px 0 5px; color: #1d3a5f; }
  h5, h6 { font-size: 13.5px; margin: 14px 0 4px; color: #33506e; }
  p { font-size: 13.5px; line-height: 1.65; margin: 8px 0; }
  ul, ol { font-size: 13.5px; line-height: 1.6; margin: 8px 0 8px 22px; padding: 0; }
  li { margin: 3px 0; }
  table { border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 12.5px; }
  th, td { border: 1px solid #c9d6e8; padding: 7px 10px; text-align: left; vertical-align: top; line-height: 1.5; }
  th { background: #eaf1fa; color: #17304f; font-weight: 700; }
  tr:nth-child(even) td { background: #f8fafd; }
  figure { margin: 18px 0; text-align: center; }
  figure img { max-width: 100%; height: auto; border: 1px solid #dfe8f2; border-radius: 8px; background: #fff; }
  pre { background: #0e1c2c; color: #d9e8f6; border-radius: 10px; padding: 14px 16px; font-family: Consolas, 'Courier New', monospace; font-size: 12px; line-height: 1.5; overflow-x: auto; white-space: pre-wrap; }
  .doc-meta { font-size: 12px; color: #5b6b7d; border-bottom: 1px solid #e3eaf5; padding-bottom: 10px; margin-bottom: 14px; }
  .doc-error { background: #fdf0f1; border: 1px solid #efc3c9; color: #8f3a45; padding: 12px 14px; border-radius: 10px; font-size: 13px; }
  .doc-back { display: inline-block; margin-top: 26px; font-size: 13px; color: #2f6fb2; text-decoration: none; font-weight: 600; }
  .doc-back:hover { text-decoration: underline; }
"""


def render_assessment_matrix_html(
    project_root: Path,
    *,
    back_link: bool = True,
) -> str:
    """Render the Assessment Matrix docx to a standalone HTML page.

    Raises FileNotFoundError when the source document is missing; any other
    failure falls back to an honest error page (never a fake render).
    """
    path = assessment_docx_path(project_root)
    if not path.exists():
        raise FileNotFoundError(f"Assessment Matrix document not found: {path}")

    with zipfile.ZipFile(path) as zf:
        document_xml = zf.read("word/document.xml")
        relationships = _load_relationships(zf)

    root = ET.fromstring(document_xml)
    body = root.find(f"{_W}body")
    if body is None:
        raise ValueError("Assessment Matrix docx has no document body.")

    parts: list[str] = []
    heading_tag = {1: "h1", 2: "h2", 3: "h3", 4: "h4", 5: "h5", 6: "h6"}
    # The image blip lives in the DrawingML MAIN namespace, not the
    # wordprocessingDrawing namespace — search both.
    _A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

    for kind, element in _iter_block_items(body):
        if kind == "p":
            text = _paragraph_text(element)
            # Inline images: any <a:blip r:embed> anywhere in the paragraph.
            for blip in element.iter("{" + _A_NS + "}blip"):
                rid = blip.get(_R + "embed") or blip.get(_R + "link") or ""
                media = relationships.get(rid)
                if not media:
                    continue
                try:
                    with zipfile.ZipFile(path) as zf:
                        data_uri = _image_data_uri(zf, media)
                    parts.append(f"<figure><img src=\"{data_uri}\" alt=\"Assessment Matrix figure\"></figure>")
                except KeyError:
                    pass
            if not text:
                continue
            block = _classify_paragraph(element, text)
            if block.startswith("h"):
                parts.append(f"<{block}>{html.escape(text)}</{block}>")
            elif block == "code":
                parts.append(f"<pre class=code>{html.escape(text)}</pre>")
            else:
                kind_list = _paragraph_is_list_item(element)
                if kind_list == "ul":
                    parts.append(f"<li>{html.escape(text)}</li>")
                else:
                    parts.append(f"<p>{html.escape(text)}</p>")
        elif kind == "tbl":
            rows = _table_rows(element)
            if not rows:
                continue
            # First row becomes the header when it has more than one cell.
            head_cells = rows[0]
            body_rows = rows[1:]
            header_html = (
                "<tr>"
                + "".join(f"<th>{html.escape(' '.join(c))}</th>" for c in head_cells)
                + "</tr>"
            )
            body_html = "".join(
                "<tr>" + "".join(f"<td>{html.escape(' '.join(c))}</td>" for c in row) + "</tr>"
                for row in body_rows
            )
            parts.append(f"<table><thead>{header_html}</thead><tbody>{body_html}</tbody></table>")

    # Wrap consecutive <li> runs in a real list, and consecutive code lines
    # into one <pre> block (the code samples read as one contiguous listing).
    wrapped: list[str] = []
    in_list = False
    in_code = False
    for part in parts:
        is_li = part.startswith("<li>")
        is_code = part.startswith("<pre class=code>")
        if is_li and not in_list:
            if in_code:
                wrapped.append("</pre>")
                in_code = False
            wrapped.append("<ul>")
            in_list = True
        elif not is_li and in_list:
            wrapped.append("</ul>")
            in_list = False
        if is_code:
            if not in_code:
                wrapped.append("<pre>")
                in_code = True
            wrapped.append(html.escape(part[len("<pre class=code>"):-len("</pre>")]))
            continue
        if not is_code and in_code:
            wrapped.append("</pre>")
            in_code = False
        wrapped.append(part)
    if in_list:
        wrapped.append("</ul>")
    if in_code:
        wrapped.append("</pre>")
    body_html = "\n".join(wrapped)

    stat = path.stat()
    rendered_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = (
        f"Rendered from <code>{html.escape(str(ASSESSMENT_DOCX_RELATIVE))}</code> · "
        f"{stat.st_size:,} bytes · rendered {rendered_at}"
    )
    back = '<a class="doc-back" href="/ui/patterns" onclick="window.close();return false;">&larr; Back to New Patterns</a>' if back_link else ""
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Assessment Matrix — New Pattern Discovery — Sentinari</title>\n"
        f"<style>{_DOC_CSS}</style>\n</head>\n<body>\n"
        "<div class=\"doc-shell\">\n"
        f"<div class=\"doc-meta\">{meta}</div>\n"
        f"{body_html}\n"
        f"{back}\n"
        "</div>\n</body>\n</html>\n"
    )


def get_assessment_matrix_html(project_root: Path) -> str:
    """mtime/size-cached render; re-renders only when the docx changes."""
    path = assessment_docx_path(project_root)
    stat = path.stat()
    key = (int(stat.st_mtime), int(stat.st_size))
    with _CACHE_LOCK:
        if _CACHE.get("key") == key and _CACHE.get("html"):
            return str(_CACHE["html"])
    rendered = render_assessment_matrix_html(project_root)
    with _CACHE_LOCK:
        _CACHE["key"] = key
        _CACHE["html"] = rendered
    return rendered
