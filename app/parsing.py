from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader
import requests

from .chunking import normalize_text
from .config import get_project_root, get_settings


TEXT_LIKE_SUFFIXES = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
}
CODE_LIKE_SUFFIXES = {
    ".bat",
    ".cmd",
    ".css",
    ".cs",
    ".csproj",
    ".js",
    ".jsx",
    ".ps1",
    ".psm1",
    ".py",
    ".sh",
    ".sln",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
}
CODE_LANGUAGE_HINTS = {
    ".bat": "batch",
    ".cmd": "batch",
    ".css": "css",
    ".cs": "csharp",
    ".csproj": "msbuild",
    ".js": "javascript",
    ".jsx": "react-jsx",
    ".ps1": "powershell",
    ".psm1": "powershell-module",
    ".py": "python",
    ".sh": "shell",
    ".sln": "solution",
    ".sql": "sql",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "react-tsx",
}

PAGE_NUMBER_LINE = re.compile(r"^\s*(?:page\s*)?\d+(?:\s*(?:of|/)\s*\d+)?\s*$", re.IGNORECASE)
NOISE_LINE_PATTERNS = [
    re.compile(r"\bisbn\b", re.IGNORECASE),
    re.compile(r"\ball rights reserved\b", re.IGNORECASE),
    re.compile(r"\bcopyright\b", re.IGNORECASE),
    re.compile(r"\bprinted in\b", re.IGNORECASE),
]
_DOCLING_RUNTIME_AVAILABLE: bool | None = None
_DOCLING_RETRY_AFTER_EPOCH = 0.0
_DOCLING_FAILURE_COOLDOWN_SECONDS = 900


def parse_document_from_path(path: str, strip_noise: bool = True) -> dict[str, Any]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    allow_noise_stripping = True

    if suffix == ".pdf":
        parsed = _parse_pdf(file_path)
    elif suffix == ".docx":
        parsed = _parse_docx(file_path)
    elif suffix in {".html", ".htm"}:
        html = file_path.read_text(encoding="utf-8", errors="ignore")
        parsed = _parse_html(html, default_title=file_path.stem)
    elif suffix in CODE_LIKE_SUFFIXES:
        raw = file_path.read_text(encoding="utf-8", errors="ignore")
        parsed = _parse_code_like(raw, file_path)
        allow_noise_stripping = False
    elif suffix in TEXT_LIKE_SUFFIXES:
        raw = file_path.read_text(encoding="utf-8", errors="ignore")
        parsed = _parse_text_like(raw, default_title=file_path.stem, source_type="text")
    else:
        raw = file_path.read_text(encoding="utf-8", errors="ignore")
        parsed = _parse_text_like(raw, default_title=file_path.stem, source_type="text")

    text = str(parsed.get("text") or "")
    if strip_noise and allow_noise_stripping:
        text = _strip_noise_from_body(
            text,
            authors=str(parsed.get("authors") or ""),
            publisher=str(parsed.get("publisher") or ""),
        )

    parsed["text"] = normalize_text(text)
    parsed["title"] = normalize_text(str(parsed.get("title") or file_path.stem)) or file_path.stem
    parsed["authors"] = normalize_text(str(parsed.get("authors") or ""))
    parsed["publisher"] = normalize_text(str(parsed.get("publisher") or ""))
    parsed["published_date"] = normalize_text(str(parsed.get("published_date") or ""))
    return parsed


def _parse_code_like(raw: str, path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    language = CODE_LANGUAGE_HINTS.get(suffix, suffix.lstrip(".") or "code")
    try:
        relative_path = path.resolve().relative_to(get_project_root()).as_posix()
    except Exception:
        relative_path = path.resolve().as_posix()
    header = [
        f"# Code File: {path.name}",
        f"Path: {relative_path}",
        f"Language: {language}",
        "",
    ]
    return {
        "text": "\n".join(header) + raw,
        "source_type": "code",
        "title": relative_path,
        "authors": "",
        "publisher": "",
        "published_date": "",
        "extra_metadata": {
            "code_language": language,
            "code_suffix": suffix,
            "relative_path": relative_path,
        },
    }


def _clean_extracted_text(raw: str) -> str:
    text = (raw or "").replace("\u0000", " ").replace("\ufeff", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def read_text_from_path(path: str) -> tuple[str, str]:
    parsed = parse_document_from_path(path, strip_noise=True)
    return str(parsed.get("text") or ""), str(parsed.get("source_type") or "text")


def extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.extract()
    return normalize_text(soup.get_text(separator=" ", strip=True))


def extract_title_from_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    if soup.title and soup.title.string:
        return normalize_text(soup.title.string)
    og_title = _extract_meta_content(soup, ["og:title", "twitter:title"])
    if og_title:
        return og_title
    return ""


def parse_document_from_html(html: str, default_title: str = "web source", strip_noise: bool = True) -> dict[str, Any]:
    parsed = _parse_html(html, default_title=default_title)
    text = str(parsed.get("text") or "")
    if strip_noise:
        text = _strip_noise_from_body(
            text,
            authors=str(parsed.get("authors") or ""),
            publisher=str(parsed.get("publisher") or ""),
        )
    parsed["text"] = normalize_text(text)
    return parsed


def _polish_pdf_text(text: str) -> str:
    """Quality layer for extracted PDF text (owner's clean-text directive).

    Repairs the classic extraction artifacts so chunks and embeddings read
    like prose rather than a PDF wire dump:
    1. re-joins words a line break split with a hyphen (``thermo-\ndynamic``
       -> ``thermodynamic``)
    2. merges single-newline soft wraps into spaces (paragraph boundaries —
       blank lines — are preserved)
    3. collapses runs of spaces/tabs
    4. drops leftover page-artifact lines (bare numbers, ``Page 3 of 12``)
    """
    if not text:
        return text
    # 1. de-hyphenate words broken across line breaks
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # 2. drop page-artifact lines while they are still standalone lines
    #    (before soft-wrap joining could fold them into real paragraphs)
    text = "\n".join(
        ln for ln in text.split("\n") if not PAGE_NUMBER_LINE.match(ln.strip())
    )
    # 3. single newlines are soft wraps; paragraphs keep their blank line
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    # 4. collapse whitespace runs
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _parse_pdf(path: Path) -> dict[str, Any]:
    meta = {}
    try:
        reader = PdfReader(str(path))
        meta = reader.metadata or {}
    except Exception:
        reader = None

    title = _first_non_empty(_meta_get(meta, "/Title"), path.stem)
    authors = _first_non_empty(_meta_get(meta, "/Author"), _meta_get(meta, "author"))
    publisher = _first_non_empty(
        _meta_get(meta, "/Publisher"),
        _meta_get(meta, "/Producer"),
        _meta_get(meta, "/Creator"),
        _meta_get(meta, "producer"),
        _meta_get(meta, "creator"),
    )
    published_date = _normalize_date_string(
        _first_non_empty(_meta_get(meta, "/CreationDate"), _meta_get(meta, "/ModDate"))
    )

    poppler_text, poppler_engine = _extract_pdf_text_via_poppler(path)
    if len(poppler_text.strip()) >= 80:
        extra_metadata = _to_safe_meta_dict(meta)
        extra_metadata["pdf_preprocess_engine"] = poppler_engine or "poppler"
        return {
            "text": _polish_pdf_text(poppler_text),
            "source_type": "pdf",
            "title": title,
            "authors": authors,
            "publisher": publisher,
            "published_date": published_date,
            "extra_metadata": extra_metadata,
        }

    pypdf_text = ""
    if reader is not None:
        per_page_lines: list[list[str]] = []
        edge_line_frequency: dict[str, int] = {}
        for page in reader.pages:
            try:
                raw_page = page.extract_text() or ""
            except Exception:
                raw_page = ""
            lines = _split_lines(raw_page)
            if not lines:
                continue
            per_page_lines.append(lines)
            for edge in lines[:2] + lines[-2:]:
                key = _canonical_line(edge)
                if not key:
                    continue
                edge_line_frequency[key] = edge_line_frequency.get(key, 0) + 1

        repetitive_edges = {
            line
            for line, count in edge_line_frequency.items()
            if count >= max(3, len(per_page_lines) // 3) and len(line) <= 100
        }

        body_lines: list[str] = []
        for lines in per_page_lines:
            for raw in lines:
                canonical = _canonical_line(raw)
                if not canonical:
                    continue
                if canonical in repetitive_edges:
                    continue
                body_lines.append(raw.strip())
        pypdf_text = _polish_pdf_text("\n".join(body_lines))
        if len(pypdf_text.strip()) >= 80:
            extra_metadata = _to_safe_meta_dict(meta)
            extra_metadata["pdf_preprocess_engine"] = "pypdf"
            return {
                "text": pypdf_text,
                "source_type": "pdf",
                "title": title,
                "authors": authors,
                "publisher": publisher,
                "published_date": published_date,
                "extra_metadata": extra_metadata,
            }

    # Heavy fallback chain (docling / stirling / easyocr) only for scanned/image PDFs
    preprocessed_text, preprocess_engine = _extract_pdf_text_via_preprocessor(path)
    if preprocessed_text.strip():
        extra_metadata = _to_safe_meta_dict(meta)
        extra_metadata["pdf_preprocess_engine"] = preprocess_engine
        return {
            "text": _polish_pdf_text(preprocessed_text),
            "source_type": "pdf",
            "title": title,
            "authors": authors,
            "publisher": publisher,
            "published_date": published_date,
            "extra_metadata": extra_metadata,
        }

    return {
        "text": pypdf_text or _polish_pdf_text(poppler_text),
        "source_type": "pdf",
        "title": title,
        "authors": authors,
        "publisher": publisher,
        "published_date": published_date,
        "extra_metadata": _to_safe_meta_dict(meta),
    }


def _extract_pdf_text_via_preprocessor(path: Path) -> tuple[str, str]:
    settings = get_settings()
    preprocess = settings.get("pdf_preprocess", {})
    if not isinstance(preprocess, dict):
        return "", ""

    engine = str(preprocess.get("engine") or "").strip().lower()
    if engine == "poppler":
        poppler_text, poppler_engine = _extract_pdf_text_via_poppler(path, preprocess=preprocess)
        if poppler_text.strip():
            return poppler_text, poppler_engine
        return "", ""
    if engine == "pipeline":
        # Try Poppler first (fastest for text-based PDFs)
        poppler_text, poppler_engine = _extract_pdf_text_via_poppler(path, preprocess=preprocess)
        if poppler_text.strip():
            return poppler_text, poppler_engine
        # Fallback to Docling (AI-based, better for scanned/image PDFs)
        docling_text = _extract_pdf_text_via_docling(path, preprocess=preprocess)
        if docling_text.strip():
            return docling_text, "docling_fallback"
        # Fallback to Stirling service if available
        stirling_fallback_text = _extract_pdf_text_via_stirling(path, preprocess=preprocess)
        if stirling_fallback_text.strip():
            return stirling_fallback_text, "stirling_fallback"
        # Final fallback to OCR for image-based PDFs
        ocr_text = _extract_pdf_text_via_ocr(path)
        if ocr_text.strip():
            return ocr_text, "easyocr_fallback"
        return "", ""
    if engine == "docling":
        docling_text = _extract_pdf_text_via_docling(path, preprocess=preprocess)
        if docling_text.strip():
            return docling_text, "docling"
        stirling_fallback_text = _extract_pdf_text_via_stirling(path, preprocess=preprocess)
        if stirling_fallback_text.strip():
            return stirling_fallback_text, "stirling_fallback"
        ocr_text = _extract_pdf_text_via_ocr(path)
        if ocr_text.strip():
            return ocr_text, "easyocr_fallback"
        return "", ""
    if engine == "easyocr":
        ocr_text = _extract_pdf_text_via_ocr(path)
        if ocr_text.strip():
            return ocr_text, "easyocr"
        return "", ""
    if engine != "stirling":
        return "", ""

    stirling_text = _extract_pdf_text_via_stirling(path, preprocess=preprocess)
    if stirling_text.strip():
        return stirling_text, "stirling"
    return "", ""


def _resolve_executable(raw_command: str, fallbacks: list[str] | None = None) -> str:
    candidates: list[str] = []
    text = str(raw_command or "").strip()
    if text:
        candidates.append(text)
    for fallback in (fallbacks or []):
        fb = str(fallback or "").strip()
        if fb:
            candidates.append(fb)

    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        p = Path(candidate).expanduser()
        if p.exists() and p.is_file():
            return str(p)
    return ""


def _sanitize_pdf_via_dangerzone(path: Path, cfg: dict[str, Any], tmp_dir: str) -> tuple[Path, str]:
    if not bool(cfg.get("dangerzone_sanitize_first", False)):
        return path, ""

    dz_bin = _resolve_executable(
        str(cfg.get("dangerzone_command") or "dangerzone-cli"),
        ["dangerzone-cli", "dangerzone"],
    )
    if not dz_bin:
        return path, ""

    timeout_seconds = max(20, int(cfg.get("dangerzone_timeout_seconds") or 180))
    output_pdf = Path(tmp_dir) / f"{path.stem}.dangerzone.safe.pdf"
    ocr_lang = str(cfg.get("dangerzone_ocr_lang") or "").strip().lower()

    cmd: list[str] = [
        dz_bin,
        "--output-filename",
        str(output_pdf),
    ]
    if ocr_lang:
        cmd.extend(["--ocr-lang", ocr_lang])
    cmd.append(str(path))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if proc.returncode == 0 and output_pdf.exists():
            return output_pdf, "dangerzone"
    except Exception:
        return path, ""
    return path, ""


def _extract_pdf_text_via_poppler(path: Path, preprocess: dict[str, Any] | None = None) -> tuple[str, str]:
    settings = get_settings()
    cfg = preprocess if isinstance(preprocess, dict) else settings.get("pdf_preprocess", {})
    if not isinstance(cfg, dict):
        return "", ""

    engine = str(cfg.get("engine") or "").strip().lower()
    if engine not in {"poppler", "pipeline"}:
        return "", ""

    timeout_seconds = max(5, int(cfg.get("timeout_seconds") or 45))
    poppler_bin = _resolve_executable(
        str(cfg.get("poppler_command") or "pdftotext"),
        ["pdftotext"],
    )
    if not poppler_bin:
        return "", ""

    use_layout = bool(cfg.get("poppler_layout", True))
    flatten_first = bool(cfg.get("ghostscript_flatten_first", False))
    source_pdf = path
    labels: list[str] = []

    try:
        with tempfile.TemporaryDirectory(prefix="smi_pdf_preprocess_") as tmp_dir:
            source_pdf, dz_label = _sanitize_pdf_via_dangerzone(source_pdf, cfg, tmp_dir)
            if dz_label:
                labels.append(dz_label)

            if flatten_first:
                gs_bin = _resolve_executable(
                    str(cfg.get("ghostscript_command") or "gswin64c"),
                    ["gswin64c", "gs", "gswin32c"],
                )
                if gs_bin:
                    flat_pdf = Path(tmp_dir) / f"{path.stem}.flattened.pdf"
                    gs_compatibility = str(cfg.get("ghostscript_compatibility") or "1.4").strip() or "1.4"
                    gs_pdf_settings = str(cfg.get("ghostscript_pdf_settings") or "/printer").strip() or "/printer"
                    gs_cmd = [
                        gs_bin,
                        "-sDEVICE=pdfwrite",
                        f"-dCompatibilityLevel={gs_compatibility}",
                        f"-dPDFSETTINGS={gs_pdf_settings}",
                        "-dNOPAUSE",
                        "-dQUIET",
                        "-dBATCH",
                        "-dSAFER",
                        f"-sOutputFile={flat_pdf}",
                        str(path),
                    ]
                    gs_proc = subprocess.run(
                        gs_cmd,
                        capture_output=True,
                        text=True,
                        timeout=timeout_seconds,
                        check=False,
                    )
                    if gs_proc.returncode == 0 and flat_pdf.exists():
                        source_pdf = flat_pdf
                        labels.append("ghostscript")

            poppler_cmd: list[str] = [poppler_bin, "-enc", "UTF-8"]
            if use_layout:
                poppler_cmd.append("-layout")
            poppler_cmd.extend([str(source_pdf), "-"])

            proc = subprocess.run(
                poppler_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=timeout_seconds,
                check=False,
            )
            if proc.returncode != 0:
                return "", ""
            engine_label = "_".join(labels + ["poppler"]) if labels else "poppler"
            return _clean_extracted_text(str(proc.stdout or "")), engine_label
    except Exception:
        return "", ""


def _extract_pdf_text_via_docling(path: Path, preprocess: dict[str, Any] | None = None) -> str:
    global _DOCLING_RUNTIME_AVAILABLE
    global _DOCLING_RETRY_AFTER_EPOCH

    settings = get_settings()
    cfg = preprocess if isinstance(preprocess, dict) else settings.get("pdf_preprocess", {})
    if not isinstance(cfg, dict):
        return ""

    engine = str(cfg.get("engine") or "").strip().lower()
    if engine not in {"docling", "pipeline"}:
        return ""

    output_format = str(cfg.get("docling_format") or "markdown").strip().lower()
    if output_format not in {"markdown", "text"}:
        output_format = "markdown"

    now = time.time()
    if _DOCLING_RUNTIME_AVAILABLE is False and now < _DOCLING_RETRY_AFTER_EPOCH:
        return ""

    timeout_seconds = max(10, int(cfg.get("timeout_seconds") or 45))
    helper = (
        "import sys\n"
        "from docling.document_converter import DocumentConverter\n"
        "source = sys.argv[1]\n"
        "fmt = (sys.argv[2] or 'markdown').strip().lower()\n"
        "if fmt not in {'markdown','text'}:\n"
        "    fmt = 'markdown'\n"
        "converter = DocumentConverter()\n"
        "result = converter.convert(source)\n"
        "doc = getattr(result, 'document', None)\n"
        "if doc is None:\n"
        "    sys.exit(0)\n"
        "if fmt == 'text' and hasattr(doc, 'export_to_text'):\n"
        "    text = doc.export_to_text() or ''\n"
        "elif hasattr(doc, 'export_to_markdown'):\n"
        "    text = doc.export_to_markdown() or ''\n"
        "elif hasattr(doc, 'export_to_text'):\n"
        "    text = doc.export_to_text() or ''\n"
        "else:\n"
        "    text = ''\n"
        "sys.stdout.write(text if isinstance(text, str) else str(text))\n"
    )

    try:
        proc = subprocess.run(
            [sys.executable, "-c", helper, str(path), output_format],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if proc.returncode != 0:
            _DOCLING_RUNTIME_AVAILABLE = False
            _DOCLING_RETRY_AFTER_EPOCH = time.time() + _DOCLING_FAILURE_COOLDOWN_SECONDS
            return ""
        text = _clean_extracted_text(str(proc.stdout or ""))
        if text:
            _DOCLING_RUNTIME_AVAILABLE = True
            _DOCLING_RETRY_AFTER_EPOCH = 0.0
        return text
    except subprocess.TimeoutExpired:
        _DOCLING_RUNTIME_AVAILABLE = False
        _DOCLING_RETRY_AFTER_EPOCH = time.time() + _DOCLING_FAILURE_COOLDOWN_SECONDS
        return ""
    except Exception:
        _DOCLING_RUNTIME_AVAILABLE = False
        _DOCLING_RETRY_AFTER_EPOCH = time.time() + _DOCLING_FAILURE_COOLDOWN_SECONDS
        return ""


def _extract_pdf_text_via_stirling(path: Path, preprocess: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    cfg = preprocess if isinstance(preprocess, dict) else settings.get("pdf_preprocess", {})
    if not isinstance(cfg, dict):
        return ""

    engine = str(cfg.get("engine") or "").strip().lower()
    if engine not in {"stirling", "docling", "pipeline"}:
        return ""

    base_url = str(cfg.get("stirling_url") or "").strip().rstrip("/")
    if not base_url:
        return ""

    timeout_seconds = int(cfg.get("timeout_seconds") or 45)
    verify_tls = bool(cfg.get("verify_tls", True))
    api_key_env = str(cfg.get("api_key_env") or "STIRLING_PDF_API_KEY").strip() or "STIRLING_PDF_API_KEY"
    api_key_header = str(cfg.get("api_key_header") or "X-API-KEY").strip() or "X-API-KEY"

    headers: dict[str, str] = {}
    api_key = str((os.environ.get(api_key_env) or "")).strip()
    if api_key:
        headers[api_key_header] = api_key

    try:
        with path.open("rb") as f:
            files = {"fileInput": (path.name, f, "application/pdf")}
            data = {"outputFormat": "txt"}
            resp = requests.post(
                f"{base_url}/api/v1/convert/pdf/text",
                files=files,
                data=data,
                headers=headers,
                timeout=max(5, timeout_seconds),
                verify=verify_tls,
            )
        if resp.status_code < 200 or resp.status_code >= 300:
            return ""
        content_type = str(resp.headers.get("content-type") or "").lower()
        if "application/json" in content_type:
            return ""
        return _clean_extracted_text(resp.text)
    except Exception:
        return ""


def _extract_pdf_text_via_ocr(path: Path) -> str:
    """Extract text from PDF using EasyOCR as fallback for image-based PDFs."""
    try:
        import easyocr
    except ImportError:
        return ""

    try:
        from pdf2image import convert_from_path
    except ImportError:
        return ""

    try:
        # Convert PDF to images
        images = convert_from_path(str(path), first_page=1, last_page=10)
        if not images:
            return ""

        # Initialize reader (uses GPU if available via num_gpu setting)
        reader = easyocr.Reader(['en'], gpu=False)

        extracted_text: list[str] = []
        for img in images:
            try:
                results = reader.readtext(img)
                page_text = "\n".join([text[1] for text in results if text[1].strip()])
                if page_text.strip():
                    extracted_text.append(page_text)
            except Exception:
                continue

        return "\n".join(extracted_text)
    except Exception:
        return ""


def _parse_docx(path: Path) -> dict[str, Any]:
    doc = Document(str(path))
    core = doc.core_properties
    title = _first_non_empty(core.title, path.stem)
    authors = _first_non_empty(core.author)
    # docx has no strict publisher field; fallback to category/subject where available.
    publisher = _first_non_empty(getattr(core, "category", ""), getattr(core, "subject", ""))
    published_date = _normalize_datetime(core.created)
    text = "\n".join(p.text.strip() for p in doc.paragraphs if p.text and p.text.strip())

    return {
        "text": text,
        "source_type": "docx",
        "title": title,
        "authors": authors,
        "publisher": publisher,
        "published_date": published_date,
        "extra_metadata": {
            "last_modified_by": getattr(core, "last_modified_by", "") or "",
            "modified": _normalize_datetime(getattr(core, "modified", None)),
        },
    }


def _parse_html(html: str, default_title: str) -> dict[str, Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    title = _first_non_empty(extract_title_from_html(html), default_title)
    authors = _extract_meta_content(
        soup,
        ["author", "article:author", "dc.creator", "citation_author"],
    )
    publisher = _extract_meta_content(
        soup,
        ["publisher", "dc.publisher", "og:site_name", "application-name"],
    )
    published_date = _normalize_date_string(
        _extract_meta_content(
            soup,
            ["article:published_time", "date", "dc.date", "citation_publication_date", "pubdate"],
        )
    )
    text = extract_text_from_html(html)
    return {
        "text": text,
        "source_type": "html",
        "title": title,
        "authors": authors,
        "publisher": publisher,
        "published_date": published_date,
        "extra_metadata": {},
    }


def _parse_text_like(raw: str, default_title: str, source_type: str) -> dict[str, Any]:
    lines = _split_lines(raw)
    title = default_title
    title_locked = False
    authors = ""
    publisher = ""
    published_date = ""
    kept: list[str] = []

    for idx, line in enumerate(lines):
        text = line.strip()
        lower = text.lower()
        if idx < 35:
            if not title_locked and lower.startswith("# "):
                maybe_title = text[2:].strip()
                if maybe_title:
                    title = maybe_title
                    title_locked = True
                continue
            if lower.startswith("title:"):
                value = text.split(":", 1)[1].strip()
                if value:
                    title = value
                    title_locked = True
                continue
            if lower.startswith("author:"):
                authors = text.split(":", 1)[1].strip()
                continue
            if lower.startswith("publisher:"):
                publisher = text.split(":", 1)[1].strip()
                continue
            if lower.startswith("date:") or lower.startswith("published:"):
                published_date = _normalize_date_string(text.split(":", 1)[1].strip())
                continue
        kept.append(text)

    return {
        "text": "\n".join(kept),
        "source_type": source_type,
        "title": title,
        "authors": authors,
        "publisher": publisher,
        "published_date": published_date,
        "extra_metadata": {},
    }


def _strip_noise_from_body(text: str, authors: str = "", publisher: str = "") -> str:
    lines = _split_lines(text)
    author_key = _canonical_line(authors)
    publisher_key = _canonical_line(publisher)
    cleaned: list[str] = []

    for idx, raw in enumerate(lines):
        line = raw.strip()
        canonical = _canonical_line(line)
        if not canonical:
            continue
        if PAGE_NUMBER_LINE.match(line):
            continue
        if idx < 35 and (canonical == author_key or canonical == publisher_key):
            continue
        if idx < 35 and (
            canonical.startswith("author:")
            or canonical.startswith("publisher:")
            or canonical.startswith("table of contents")
            or canonical.startswith("contents")
        ):
            continue
        if any(pattern.search(line) for pattern in NOISE_LINE_PATTERNS):
            continue
        cleaned.append(line)

    return "\n".join(cleaned)


def _meta_get(meta: Any, key: str) -> str:
    try:
        if isinstance(meta, dict):
            value = meta.get(key)
        else:
            value = getattr(meta, key.lstrip("/"), None)
        return normalize_text(str(value or ""))
    except Exception:
        return ""


def _to_safe_meta_dict(meta: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        keys = list(meta.keys()) if hasattr(meta, "keys") else []
        for key in keys:
            text_key = str(key)
            value = ""
            try:
                value = normalize_text(str(meta.get(key) or ""))
            except Exception:
                value = ""
            if text_key and value:
                result[text_key] = value
    except Exception:
        return {}
    return result


def _extract_meta_content(soup: BeautifulSoup, names: list[str]) -> str:
    wanted = {n.lower() for n in names}
    for tag in soup.find_all("meta"):
        name = str(tag.attrs.get("name") or tag.attrs.get("property") or "").strip().lower()
        if not name or name not in wanted:
            continue
        value = str(tag.attrs.get("content") or "").strip()
        if value:
            return normalize_text(value)
    return ""


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").replace("\r", "\n").split("\n") if line.strip()]


def _canonical_line(text: str) -> str:
    return normalize_text((text or "").lower())


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = normalize_text(str(value or ""))
        if text:
            return text
    return ""


def _normalize_datetime(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    return _normalize_date_string(str(value))


def _normalize_date_string(raw: str) -> str:
    text = normalize_text(raw)
    if not text:
        return ""

    # PDF date format: D:YYYYMMDD...
    pdf_match = re.search(r"D:(\d{4})(\d{2})?(\d{2})?", text)
    if pdf_match:
        year = pdf_match.group(1)
        month = pdf_match.group(2) or "01"
        day = pdf_match.group(3) or "01"
        return f"{year}-{month}-{day}"

    # ISO-like YYYY-MM-DD or YYYY/MM/DD
    iso_match = re.search(r"(\d{4})[-/](\d{2})[-/](\d{2})", text)
    if iso_match:
        return f"{iso_match.group(1)}-{iso_match.group(2)}-{iso_match.group(3)}"

    # Year only fallback.
    year_match = re.search(r"\b(19|20)\d{2}\b", text)
    if year_match:
        return f"{year_match.group(0)}-01-01"

    return ""
