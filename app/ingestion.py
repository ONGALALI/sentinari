from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .chunking import split_into_chunks
from .config import clamp_temperature, get_settings
from .db import get_connection, library_connection, reset_document_chunks
from . import load_progress
from .llm_firewall import assert_runtime_llm_policy
from .llm_boundary import is_ollama_runtime_probe_disabled
from .ollama_client import OllamaClient
from .parsing import parse_document_from_html, parse_document_from_path
from .taxonomy import infer_metadata_from_taxonomy_path


METADATA_COLUMNS = (
    "module",
    "topic",
    "language",
    "license",
    "published_date",
    "authors",
    "publisher",
    "scientific_field",
    "vocational_discipline",
    "source_collection",
)


def build_ollama_client():
    """Build the app-wide LLM client from settings.

    The name is historical — every module imports it. The backend is chosen
    by ``runtime_llm.client_backend``: ``ollama_client`` (the legacy direct
    Ollama client, current default until the cord-cut is flipped) or
    ``gateway`` (GatewayBackedClient — any provider, no Ollama dependency).
    Both expose the same surface, so callers never change.
    """
    settings = get_settings()
    assert_runtime_llm_policy(settings)
    backend = str((settings.get("runtime_llm") or {}).get("client_backend") or "ollama_client").strip().lower()
    if backend == "gateway":
        from .llm_gateway import GatewayBackedClient

        return GatewayBackedClient()
    llm = settings.get("llm", {})
    temperature = clamp_temperature(llm.get("temperature"), settings=settings)
    return OllamaClient(
        base_url=str(llm.get("base_url") or "http://127.0.0.1:11434"),
        chat_model=str(llm.get("chat_model") or "SMI4:26B"),
        embedding_model=str(llm.get("embedding_model") or "nomic-embed-text"),
        temperature=temperature,
        num_ctx=int(llm.get("num_ctx") or llm.get("context_window") or 4096),
        chat_timeout_seconds=int(llm.get("chat_timeout_seconds") or 45),
        embed_timeout_seconds=int(llm.get("embed_timeout_seconds") or 20),
        max_output_tokens=int(llm.get("max_output_tokens") or 256),
        num_gpu=None if llm.get("num_gpu") is None else int(llm.get("num_gpu")),
        keep_alive=str(llm.get("keep_alive") or "").strip() or None,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive_file(source_path: Path, checksum: str) -> str:
    settings = get_settings()
    archive_root = Path(settings["paths"]["archive_root"])
    day_folder = archive_root / datetime.now(UTC).strftime("%Y-%m-%d")
    day_folder.mkdir(parents=True, exist_ok=True)
    safe_name = f"{checksum}_{source_path.name}"
    target = day_folder / safe_name
    if not target.exists():
        shutil.copy2(source_path, target)
    return str(target.resolve())


def _archive_url_content(url: str, html: str, checksum: str) -> str:
    settings = get_settings()
    archive_root = Path(settings["paths"]["archive_root"])
    day_folder = archive_root / datetime.now(UTC).strftime("%Y-%m-%d") / "web"
    day_folder.mkdir(parents=True, exist_ok=True)
    host = (urlparse(url).hostname or "web").replace(":", "_")
    target = day_folder / f"{checksum}_{host}.html"
    if not target.exists():
        target.write_text(html, encoding="utf-8", errors="ignore")
    return str(target.resolve())


def _ensure_source_id(conn: sqlite3.Connection, requested: str | None) -> str:
    if requested and requested.strip():
        source_id = requested.strip()
        existing = conn.execute(
            "SELECT 1 FROM documents WHERE source_id = ?;",
            (source_id,),
        ).fetchone()
        if existing is None:
            return source_id

    while True:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        candidate = f"SRC-{stamp[-12:]}"
        existing = conn.execute(
            "SELECT 1 FROM documents WHERE source_id = ?;",
            (candidate,),
        ).fetchone()
        if existing is None:
            return candidate


def _token_estimate(text: str) -> int:
    return max(1, int(len((text or "").split()) * 1.15))


def _sanitize_text(text: str) -> str:
    return (text or "").encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=True, default=str)


def _merge_metadata(base: dict[str, Any] | None, extracted: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in (extracted or {}, base or {}):
        for key, value in source.items():
            if value is None:
                continue
            if not str(value).strip():
                continue
            merged[key] = value
    return merged


def _metadata_values(metadata: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(metadata.get(key) for key in METADATA_COLUMNS)


def _library_for_metadata(metadata: dict[str, Any]) -> str:
    """Route a document to its physical library from its metadata."""
    from .library_router import library_name_for_field

    return library_name_for_field(
        metadata.get("scientific_field"),
        source_collection=metadata.get("source_collection"),
        module=metadata.get("module"),
        target_library=metadata.get("target_library") or metadata.get("library"),
        persona=metadata.get("persona"),
    )



def _upsert_document_with_chunks(
    conn: sqlite3.Connection,
    *,
    title: str,
    source_type: str,
    source_path: str | None,
    source_url: str | None,
    checksum: str,
    archive_path: str | None,
    text: str,
    metadata: dict[str, Any],
    embedding_model: OllamaClient | None,
) -> dict[str, Any]:
    text = _sanitize_text(text)
    existing = None
    if source_path:
        existing = conn.execute(
            """
            SELECT id, source_id
            FROM documents
            WHERE IFNULL(source_path, '') = IFNULL(?, '')
            ORDER BY id DESC
            LIMIT 1;
            """,
            (source_path,),
        ).fetchone()
    elif source_url:
        existing = conn.execute(
            """
            SELECT id, source_id
            FROM documents
            WHERE IFNULL(source_url, '') = IFNULL(?, '')
            ORDER BY id DESC
            LIMIT 1;
            """,
            (source_url,),
        ).fetchone()

    if existing is None:
        existing = conn.execute(
            """
            SELECT id, source_id
            FROM documents
            WHERE checksum = ?
              AND IFNULL(source_path, '') = IFNULL(?, '')
              AND IFNULL(source_url, '') = IFNULL(?, '')
            ORDER BY id DESC
            LIMIT 1;
            """,
            (checksum, source_path, source_url),
        ).fetchone()

    if existing:
        source_id = str(existing["source_id"])
        document_id = int(existing["id"])
    else:
        source_id = _ensure_source_id(conn, str(metadata.get("source_id") or "").strip() or None)
        document_id = None

    ingestion = get_settings().get("ingestion", {})
    chunks = split_into_chunks(
        text,
        max_chunk_chars=int(ingestion.get("max_chunk_chars") or 1100),
        overlap_chars=int(ingestion.get("chunk_overlap_chars") or 180),
        min_chunk_chars=int(ingestion.get("min_chunk_chars") or 220),
    )
    embeddings: list[list[float] | None] = [None] * len(chunks)
    if embedding_model is not None:
        load_progress.emit(message=f"Embedding {len(chunks)} chunk(s)...")
        for idx, chunk in enumerate(chunks):
            embeddings[idx] = embedding_model.embed(chunk)
            load_progress.embed_progress(idx + 1, len(chunks))

    extra_metadata_json = _json_dumps(metadata.get("extra_metadata") or {})
    priority = int(metadata.get("priority") or 0)

    if document_id is not None:
        reset_document_chunks(conn, document_id)
        conn.execute(
            """
            UPDATE documents
            SET title = ?, source_type = ?, source_path = ?, source_url = ?, domain = ?,
                archive_path = ?, raw_char_count = ?, checksum = ?,
                module = ?, topic = ?,
                language = ?, license = ?, published_date = ?, authors = ?, publisher = ?,
                scientific_field = ?, vocational_discipline = ?, source_collection = ?,
                document_metadata_json = ?, priority = ?
            WHERE id = ?;
            """,
            (
                title,
                source_type,
                source_path,
                source_url,
                metadata.get("domain"),
                archive_path,
                len(text),
                checksum,
                *_metadata_values(metadata),
                extra_metadata_json,
                priority,
                document_id,
            ),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO documents (
                source_id, title, source_type, source_path, source_url, domain,
                module, topic,
                language, license, published_date, authors, publisher,
                scientific_field, vocational_discipline, source_collection,
                document_metadata_json, priority, checksum, archive_path, raw_char_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                source_id,
                title,
                source_type,
                source_path,
                source_url,
                metadata.get("domain"),
                *_metadata_values(metadata),
                extra_metadata_json,
                priority,
                checksum,
                archive_path,
                len(text),
            ),
        )
        document_id = int(cur.lastrowid)

    for idx, chunk in enumerate(chunks):
        chunk = _sanitize_text(chunk)
        embedding = embeddings[idx]
        cur = conn.execute(
            """
            INSERT INTO chunks (document_id, chunk_index, content, token_estimate, metadata_json, embedding_json)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (
                document_id,
                idx,
                chunk,
                _token_estimate(chunk),
                _json_dumps({"source_id": source_id}),
                json.dumps(embedding, ensure_ascii=True) if embedding else None,
            ),
        )
        chunk_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO chunk_fts (rowid, content, document_id) VALUES (?, ?, ?);",
            (chunk_id, chunk, document_id),
        )

    return {
        "document_id": document_id,
        "source_id": source_id,
        "chunk_count": len(chunks),
        "checksum": checksum,
    }


def _record_ingest_event(
    conn: sqlite3.Connection,
    source_path: str | None,
    source_type: str,
    status: str,
    error: str | None = None,
    source_id: str | None = None,
    document_id: int | None = None,
    chunk_count: int = 0,
    char_count: int = 0,
    pdf_engine: str | None = None,
    module: str | None = None,
    topic: str | None = None,
    scientific_field: str | None = None,
    vocational_discipline: str | None = None,
    source_collection: str | None = None,
    duration_ms: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO ingest_events (
            source_path, source_type, status, error, source_id, document_id, chunk_count, char_count, pdf_engine,
            module, topic, scientific_field, vocational_discipline, source_collection, duration_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            source_path,
            source_type,
            status,
            error,
            source_id,
            int(document_id) if document_id is not None else None,
            int(chunk_count),
            int(char_count),
            pdf_engine,
            module,
            topic,
            scientific_field,
            vocational_discipline,
            source_collection,
            int(duration_ms),
        ),
    )


def _metadata_text(metadata: dict[str, Any], key: str) -> str:
    return str(metadata.get(key) or "")


def _source_type_from_path(path: Path) -> str:
    return path.suffix.lower().lstrip(".") or "file"


def _pdf_engine_from_metadata(metadata: dict[str, Any]) -> str:
    extra_metadata = metadata.get("extra_metadata")
    if isinstance(extra_metadata, dict):
        return str(extra_metadata.get("pdf_preprocess_engine") or "").strip()
    return ""


def ingest_files(
    paths: list[str] | tuple[str, ...],
    metadata: dict[str, Any] | None = None,
    allow_embeddings: bool = True,
) -> dict[str, Any]:
    metadata = metadata or {}
    summary: dict[str, Any] = {"ingested": 0, "failed": 0, "items": []}
    
    # Guard against image files
    unsupported_exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff"}

    ollama = build_ollama_client()
    use_embeddings = (
        bool(allow_embeddings)
        and not is_ollama_runtime_probe_disabled()
        and ollama.is_available()
    )
    client = ollama if use_embeddings else None
    strip_noise = bool(get_settings().get("ingestion", {}).get("strip_noise", True))
    
    # --- TRACKER INITIALISATION ---
    total_files = len(paths)
    print(f"\nIngestion Started: Processing {total_files} files...\n")
    # -------------------------------
    
    # Sentinel split: each file is routed to its physical library
    # (single library: gemma = Sentinel/Guardian fields) and committed
    # against that connection.
    from .db import library_connection
    from .sentinel_firewall import firewall

    routed: dict[str, list[Path]] = {"gemma": []}
    for raw_path in paths:
        path = Path(str(raw_path)).expanduser()
        verdict = firewall.check(path, metadata)
        if not verdict["allowed"]:
            firewall.quarantine(path, verdict, metadata)
            summary["failed"] += 1
            summary["items"].append({"path": str(path), "ok": False, "error": f"firewall: {verdict['reason']}"})
            continue
        routed["gemma"].append(path)


    # SQLite allows a single writer at a time; concurrent ingestion sessions
    # (startup digestion, a Load, an upload) otherwise starve each other
    # statement-by-statement. Serialise whole digestion batches instead.
    if not _INGEST_WRITE_LOCK.acquire(blocking=False):
        load_progress.stage("digest", "Waiting for another ingestion to finish — Sentinel digests one batch at a time...")
        _INGEST_WRITE_LOCK.acquire()
    try:
        _ingest_files_locked(routed, metadata, client, strip_noise, summary, unsupported_exts)
    finally:
        _INGEST_WRITE_LOCK.release()

    # --- FINAL CLEAN COMPLETION SUMMARY ---
    print(f"\n\nDigestion Complete! Successfully Ingested: {summary['ingested']} | Failed: {summary['failed']}\n")
    # --------------------------------------

    return summary


_INGEST_WRITE_LOCK = threading.Lock()


def _ingest_files_locked(
    routed: dict[str, list[Path]],
    metadata: dict[str, Any],
    client: Any,
    strip_noise: bool,
    summary: dict[str, Any],
    unsupported_exts: set[str],
) -> None:
    for library_name, lib_paths in routed.items():
        if not lib_paths:
            continue
        lib_total = len(lib_paths)
        print(f"\n[library:{library_name}] digesting {lib_total} file(s)...")
        with library_connection(library_name) as conn:
            # Generous write window: ingestion is a long write session on a
            # library other server threads also write (startup digestion,
            # auto-ingest). The default 1 s busy timeout made each statement
            # fight the write queue during backlog storms.
            conn.execute("PRAGMA busy_timeout = 30000;")
            for index, raw_path in enumerate(lib_paths, start=1):
                path = Path(str(raw_path)).expanduser()
                started = time.perf_counter()
                load_progress.report_stage_fraction(
                    "digest",
                    index - 1,
                    lib_total,
                    f"Digesting file {index}/{lib_total}: {path.name[:60]}",
                )

                # --- PROGRESS BAR INDICATOR ---
                percent = (index / lib_total) * 100
                bar_length = 20
                filled_length = int(bar_length * index // lib_total)
                bar = '#' * filled_length + '-' * (bar_length - filled_length)

                # Prints a clean, single-line updating status bar
                print(f"\r[{bar}] {percent:.1f}% ({index}/{lib_total}) | Digesting: {path.name[:30]}...", end="", flush=True)
                # ------------------------------

                try:
                    if not path.exists() or not path.is_file():
                        raise FileNotFoundError(f"Path not found: {path}")

                    if path.suffix.lower() in unsupported_exts:
                        raise ValueError(f"File {path.name} is an image. This model does not support image input.")

                    data = path.read_bytes()

                    checksum = _sha256_bytes(data)
                    parsed = parse_document_from_path(str(path), strip_noise=strip_noise)
                    text = str(parsed.get("text") or "")
                    source_type = str(parsed.get("source_type") or "text")
                    if not text.strip():
                        pdf_engine = ""
                        extra_metadata = parsed.get("extra_metadata")
                        if isinstance(extra_metadata, dict):
                            pdf_engine = str(extra_metadata.get("pdf_preprocess_engine") or "").strip()
                        engine_info = f" [Engine: {pdf_engine}]" if pdf_engine else ""
                        raise ValueError(
                            "No extractable text found"
                            f"{engine_info}. File may be corrupted, encrypted, or image-based without OCR support."
                        )

                    archive_path = None if bool(metadata.get("skip_archive")) else _archive_file(path, checksum)
                    taxonomy_meta = infer_metadata_from_taxonomy_path(conn, path)
                    item_meta = _merge_metadata(
                        _merge_metadata(dict(metadata), taxonomy_meta),
                        {
                            "title": parsed.get("title"),
                            "authors": parsed.get("authors"),
                            "publisher": parsed.get("publisher"),
                            "published_date": parsed.get("published_date"),
                            "extra_metadata": parsed.get("extra_metadata"),
                        },
                    )
                    item_meta.setdefault("title", path.stem)
                    pdf_engine = _pdf_engine_from_metadata(item_meta)

                    result = _upsert_document_with_chunks(
                        conn,
                        title=str(item_meta.get("title") or path.stem),
                        source_type=source_type,
                        source_path=str(path.resolve()),
                        source_url=None,
                        checksum=checksum,
                        archive_path=archive_path,
                        text=text,
                        metadata=item_meta,
                        embedding_model=client,
                    )
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    _record_ingest_event(
                        conn,
                        source_path=str(path.resolve()),
                        source_type=source_type,
                        status="ok",
                        source_id=str(result.get("source_id") or ""),
                        document_id=int(result.get("document_id") or 0),
                        chunk_count=int(result.get("chunk_count") or 0),
                        char_count=len(text),
                        pdf_engine=pdf_engine,
                        module=_metadata_text(item_meta, "module"),
                        topic=_metadata_text(item_meta, "topic"),
                        scientific_field=_metadata_text(item_meta, "scientific_field"),
                        vocational_discipline=_metadata_text(item_meta, "vocational_discipline"),
                        source_collection=_metadata_text(item_meta, "source_collection"),
                        duration_ms=duration_ms,
                    )
                    summary["ingested"] += 1
                    summary["items"].append(
                        {
                            "path": str(path),
                            "ok": True,
                            "title": item_meta.get("title"),
                            "authors": item_meta.get("authors"),
                            "publisher": item_meta.get("publisher"),
                            "published_date": item_meta.get("published_date"),
                            "pdf_engine": pdf_engine,
                            "library": library_name,
                            **result,
                        }
                    )
                except Exception as ex:
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    _record_ingest_event(
                        conn,
                        source_path=str(path.resolve()),
                        source_type=_source_type_from_path(path),
                        status="failed",
                        error=str(ex),
                        module=_metadata_text(metadata, "module"),
                        topic=_metadata_text(metadata, "topic"),
                        scientific_field=_metadata_text(metadata, "scientific_field"),
                        vocational_discipline=_metadata_text(metadata, "vocational_discipline"),
                        source_collection=_metadata_text(metadata, "source_collection"),
                        duration_ms=duration_ms,
                    )
                    summary["failed"] += 1
                    summary["items"].append({"path": str(path), "ok": False, "error": str(ex)})

                conn.commit()


def ingest_url(url: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = metadata or {}
    settings = get_settings()
    runtime = settings.get("runtime", {})
    if not bool(runtime.get("allow_web_fetch", True)):
        raise PermissionError("Web fetch is disabled by configuration.")

    resp = requests.get(
        url,
        timeout=45,
        headers={"User-Agent": "VocationalLLM/1.0 (local)"},
    )
    resp.raise_for_status()
    html = resp.text[: int(settings.get("ingestion", {}).get("max_url_fetch_chars") or 250000)]
    parsed_doc = parse_document_from_html(
        html,
        default_title=url,
        strip_noise=bool(settings.get("ingestion", {}).get("strip_noise", True)),
    )
    text = str(parsed_doc.get("text") or "")
    if not text:
        raise ValueError("No extractable text from URL.")

    checksum = _sha256_bytes(html.encode("utf-8", errors="ignore"))
    archive_path = _archive_url_content(url, html, checksum)
    item_meta = _merge_metadata(
        dict(metadata),
        {
            "title": parsed_doc.get("title") or url,
            "authors": parsed_doc.get("authors"),
            "publisher": parsed_doc.get("publisher"),
            "published_date": parsed_doc.get("published_date"),
            "extra_metadata": parsed_doc.get("extra_metadata"),
        },
    )
    title = str(item_meta.get("title") or url)
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.strip().lower()
    item_meta.setdefault("domain", domain)

    ollama = build_ollama_client()
    client = ollama if (not is_ollama_runtime_probe_disabled() and ollama.is_available()) else None
    from .db import library_connection

    library_name = _library_for_metadata(item_meta)
    with library_connection(library_name) as conn:
        result = _upsert_document_with_chunks(
            conn,
            title=title,
            source_type="web",
            source_path=None,
            source_url=url,
            checksum=checksum,
            archive_path=archive_path,
            text=text,
            metadata=item_meta,
            embedding_model=client,
        )
        conn.commit()
    result["library"] = library_name

    return {
        "ok": True,
        "url": url,
        "domain": domain,
        "authors": item_meta.get("authors"),
        "publisher": item_meta.get("publisher"),
        "published_date": item_meta.get("published_date"),
        **result,
    }