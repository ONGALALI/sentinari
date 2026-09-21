import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_project_root, get_settings
from .db import get_connection
from .ingestion import ingest_files


CODING_CORPUS_SUPPORTED_SUFFIXES = {
    ".bat",
    ".cmd",
    ".css",
    ".cs",
    ".csproj",
    ".docx",
    ".html",
    ".htm",
    ".ini",
    ".js",
    ".json",
    ".log",
    ".md",
    ".pdf",
    ".ps1",
    ".psm1",
    ".py",
    ".sh",
    ".sln",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
CODING_CORPUS_IGNORED_DIRS = {
    ".git",
    ".idea",
    ".next",
    ".venv",
    ".venv312",
    "__pycache__",
    "archive",
    "bin",
    "build",
    "dist",
    "logs",
    "node_modules",
    "obj",
    "playground",
}
DEFAULT_CODING_CORPUS_ROOTS = [
    "./app",
    "./config",
    "./docs",
    "./scripts",
    "./templates",
    "./tests",
    "./README.md",
]
DEFAULT_CODING_REFERENCE_ROOTS = [
    "./data/knowledge_taxonomy/scientific_fields/computer-and-information-sciences",
]


def _normalized_roots(values: Any, defaults: list[str]) -> list[Path]:
    roots = values if isinstance(values, list) else defaults
    normalized: list[Path] = []
    seen: set[str] = set()
    for item in roots:
        text = str(item or "").strip()
        if not text:
            continue
        path = Path(text)
        if not path.is_absolute():
            path = (get_project_root() / path).resolve()
        else:
            path = path.resolve()
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        normalized.append(path)
    return normalized


def get_coding_corpus_roots(settings: dict[str, Any] | None = None) -> list[Path]:
    source = settings if isinstance(settings, dict) else get_settings()
    paths = source.get("paths", {}) if isinstance(source.get("paths"), dict) else {}
    return _normalized_roots(paths.get("coding_corpus_roots"), DEFAULT_CODING_CORPUS_ROOTS)


def get_coding_reference_roots(settings: dict[str, Any] | None = None) -> list[Path]:
    source = settings if isinstance(settings, dict) else get_settings()
    paths = source.get("paths", {}) if isinstance(source.get("paths"), dict) else {}
    return _normalized_roots(paths.get("coding_reference_roots"), DEFAULT_CODING_REFERENCE_ROOTS)


def get_coding_noise_roots(settings: dict[str, Any] | None = None) -> list[Path]:
    source = settings if isinstance(settings, dict) else get_settings()
    memory = source.get("memory", {}) if isinstance(source.get("memory"), dict) else {}
    paths = source.get("paths", {}) if isinstance(source.get("paths"), dict) else {}

    configured_log_root = str(memory.get("discussion_log_dir") or "").strip()
    if configured_log_root:
        log_root = Path(configured_log_root)
        if not log_root.is_absolute():
            log_root = (get_project_root() / log_root).resolve()
        else:
            log_root = log_root.resolve()
    else:
        taxonomy_root = Path(str(paths.get("taxonomy_root") or (get_project_root() / "data" / "knowledge_taxonomy"))).resolve()
        log_root = (taxonomy_root / "SMI_Log").resolve()

    defaults = [
        str(log_root),
        str((get_project_root() / "data" / "logs").resolve()),
        str((get_project_root() / "data" / "raw").resolve()),
        str((get_project_root() / "data" / "archive").resolve()),
    ]
    return _normalized_roots(defaults, [])


def _matches_root(path: Path, root: Path) -> bool:
    try:
        candidate = path.resolve()
        resolved_root = root.resolve()
    except Exception:
        return False
    if resolved_root.is_file():
        return os.path.normcase(str(candidate)) == os.path.normcase(str(resolved_root))
    try:
        candidate.relative_to(resolved_root)
        return True
    except Exception:
        return False


def classify_coding_source_path(path: str | Path | None, settings: dict[str, Any] | None = None) -> str:
    raw = str(path or "").strip()
    if not raw:
        return "other"
    try:
        candidate = Path(raw).resolve()
    except Exception:
        return "other"

    for root in get_coding_noise_roots(settings):
        if _matches_root(candidate, root):
            return "noise"
    for root in get_coding_corpus_roots(settings):
        if _matches_root(candidate, root):
            return "repo"
    for root in get_coding_reference_roots(settings):
        if _matches_root(candidate, root):
            return "reference"
    return "other"


def discover_coding_corpus_files(settings: dict[str, Any] | None = None) -> list[Path]:
    source = settings if isinstance(settings, dict) else get_settings()
    recursive = bool(source.get("ingestion", {}).get("recursive_scan", True)) if isinstance(source.get("ingestion"), dict) else True
    found: list[Path] = []
    seen: set[str] = set()

    def _append_if_supported(path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix not in CODING_CORPUS_SUPPORTED_SUFFIXES:
            return
        try:
            size = path.stat().st_size
            if size <= 0:
                return  # empty files have no extractable text; skipping avoids a guaranteed ingest failure
            if suffix in {".docx", ".pdf"} and size >= 4:
                magic = path.open("rb").read(4)
                # A .docx must be a zip (PK); a .pdf must start with %PDF.
                if (suffix == ".docx" and not magic.startswith(b"PK")) or (
                    suffix == ".pdf" and not magic.startswith(b"%PDF")
                ):
                    return  # corrupted or wrong-extension binary; not ingestable
        except OSError:
            return
        resolved = path.resolve()
        key = os.path.normcase(str(resolved))
        if key in seen:
            return
        seen.add(key)
        found.append(resolved)

    for root in [*get_coding_corpus_roots(source), *get_coding_reference_roots(source)]:
        if not root.exists():
            continue
        if root.is_file():
            _append_if_supported(root)
            continue

        if not root.is_dir():
            continue

        if recursive:
            for current_root, dir_names, file_names in os.walk(root):
                dir_names[:] = [name for name in dir_names if name.lower() not in CODING_CORPUS_IGNORED_DIRS]
                current_path = Path(current_root)
                for name in file_names:
                    _append_if_supported(current_path / name)
        else:
            for path in root.iterdir():
                if path.is_file():
                    _append_if_supported(path)

    return sorted(found)


def _build_coding_metadata(path: Path, settings: dict[str, Any]) -> dict[str, Any]:
    classification = classify_coding_source_path(path, settings)
    source_id = "repo"
    source_collection = "SMi Coding Corpus"
    module = "portable-codebase"
    topic = "codebase-source"
    priority = 120
    skip_archive = True

    if classification == "reference":
        source_id = "reference"
        source_collection = "Coding Reference Library"
        module = "computer-and-information-sciences"
        topic = "coding-reference-material"
        priority = 80
        skip_archive = False

    return {
        "scientific_field": "computer-and-information-sciences",
        "vocational_discipline": "software-engineering",
        "source_collection": source_collection,
        "module": module,
        "topic": topic,
        "priority": priority,
        "skip_archive": skip_archive,
        "publisher": "SMi portable coding corpus" if classification == "repo" else "",
        "domain": "local-codebase" if classification == "repo" else "local-reference",
        "license": "internal",
        "source_id": f"{source_id}:{path.name.lower()}",
    }


def _progress_snapshot_path() -> Path:
    return (get_project_root() / "data" / "coding_corpus_progress.json").resolve()


def _snapshot_roots(settings: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "coding_corpus_roots": [str(path) for path in get_coding_corpus_roots(settings)],
        "coding_reference_roots": [str(path) for path in get_coding_reference_roots(settings)],
    }


def _load_progress_snapshot(settings: dict[str, Any]) -> dict[str, Any] | None:
    path = _progress_snapshot_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    roots = _snapshot_roots(settings)
    if data.get("coding_corpus_roots") != roots["coding_corpus_roots"]:
        return None
    if data.get("coding_reference_roots") != roots["coding_reference_roots"]:
        return None
    return data


def _write_progress_snapshot(progress: dict[str, Any], settings: dict[str, Any]) -> None:
    payload = dict(progress)
    roots = _snapshot_roots(settings)
    payload["coding_corpus_roots"] = roots["coding_corpus_roots"]
    payload["coding_reference_roots"] = roots["coding_reference_roots"]
    path = _progress_snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _should_ingest(conn: sqlite3.Connection, path: Path, *, force: bool = False) -> bool:
    if force:
        return True
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    row = conn.execute(
        "SELECT file_size, mtime_utc, last_status, updated_at FROM file_ingest_state WHERE path = ?;",
        (str(path),),
    ).fetchone()
    if row is None:
        return True

    status = str(row["last_status"] or "").strip().lower()
    if int(row["file_size"] or 0) != int(stat.st_size):
        return True
    if str(row["mtime_utc"] or "") != mtime:
        return True
    if status == "ok":
        return False
    return True


def _upsert_state(conn: sqlite3.Connection, path: Path, checksum: str, status: str, error: str) -> None:
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO file_ingest_state (path, file_size, mtime_utc, checksum, last_status, last_error, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(path) DO UPDATE SET
            file_size = excluded.file_size,
            mtime_utc = excluded.mtime_utc,
            checksum = excluded.checksum,
            last_status = excluded.last_status,
            last_error = excluded.last_error,
            updated_at = datetime('now');
        """,
        (str(path), int(stat.st_size), mtime, checksum, status, error),
    )


def sync_coding_corpus(*, force: bool = False) -> dict[str, Any]:
    settings = get_settings()
    candidates = discover_coding_corpus_files(settings)
    processed = 0
    failed = 0
    skipped = 0
    items: list[dict[str, Any]] = []

    for path in candidates:
        with get_connection() as conn:
            if not _should_ingest(conn, path, force=force):
                skipped += 1
                continue

        metadata = _build_coding_metadata(path, settings)
        try:
            outcome = ingest_files([str(path)], metadata=metadata, allow_embeddings=False)
            item = (outcome.get("items") or [{}])[0]
            raw_error = str(item.get("error") or "")
            error = raw_error
            # Empty / unreadable-content files are data gaps, not sync failures.
            if not item.get("ok") and "No extractable text" in raw_error:
                checksum = str(item.get("checksum") or "")
                with get_connection() as conn:
                    _upsert_state(conn, path, checksum, "skipped", "no extractable text (empty or unsupported content)")
                    conn.commit()
                skipped += 1
                items.append(
                    {
                        "path": str(path),
                        "classification": classify_coding_source_path(path, settings),
                        "status": "skipped",
                        "title": item.get("title") or path.name,
                        "source_id": item.get("source_id") or "",
                        "error": error,
                    }
                )
                continue
            status = "ok" if bool(item.get("ok")) else "failed"
            checksum = str(item.get("checksum") or "")
            with get_connection() as conn:
                _upsert_state(conn, path, checksum, status, error)
                conn.commit()
            processed += int(outcome.get("ingested") or 0)
            failed += int(outcome.get("failed") or 0)
            items.append(
                {
                    "path": str(path),
                    "classification": classify_coding_source_path(path, settings),
                    "status": status,
                    "title": item.get("title") or path.name,
                    "source_id": item.get("source_id") or "",
                    "error": error,
                }
            )
        except Exception as ex:
            failed += 1
            with get_connection() as conn:
                _upsert_state(conn, path, "", "failed", str(ex))
                conn.commit()
            items.append(
                {
                    "path": str(path),
                    "classification": classify_coding_source_path(path, settings),
                    "status": "failed",
                    "error": str(ex),
                }
            )

    progress = get_coding_corpus_progress(settings=settings, force_refresh=True)
    return {
        "ok": True,
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
        "candidate_total": len(candidates),
        "items": items[:50],
        "progress": progress,
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
    }


def get_coding_corpus_progress(
    settings: dict[str, Any] | None = None,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else get_settings()
    if not force_refresh:
        snapshot = _load_progress_snapshot(source)
        if snapshot is not None:
            return snapshot
    candidates = discover_coding_corpus_files(source)
    candidate_keys = {os.path.normcase(str(path.resolve())): path for path in candidates}

    with get_connection() as conn:
        state_rows = conn.execute(
            "SELECT path, last_status, last_error, updated_at FROM file_ingest_state;"
        ).fetchall()
        indexed_rows = conn.execute(
            """
            SELECT d.source_path, COUNT(c.id) AS chunk_count
            FROM documents d
            LEFT JOIN chunks c ON c.document_id = d.id
            GROUP BY d.id;
            """
        ).fetchall()

    status_by_key: dict[str, tuple[str, str, str]] = {}
    for row in state_rows:
        raw_path = str(row["path"] or "").strip()
        if not raw_path:
            continue
        key = os.path.normcase(str(Path(raw_path).resolve()))
        status_by_key[key] = (
            str(row["last_status"] or "").strip().lower(),
            str(row["last_error"] or "").strip(),
            str(row["updated_at"] or "").strip(),
        )

    ingested_ok = 0
    failed = 0
    pending = 0
    tracked = 0
    repo_total = 0
    repo_ok = 0
    reference_total = 0
    reference_ok = 0
    failed_items: list[dict[str, Any]] = []
    for key, path in candidate_keys.items():
        classification = classify_coding_source_path(path, source)
        if classification == "repo":
            repo_total += 1
        elif classification == "reference":
            reference_total += 1

        state = status_by_key.get(key)
        if state:
            tracked += 1
        status = state[0] if state else ""
        if status == "ok":
            ingested_ok += 1
            if classification == "repo":
                repo_ok += 1
            elif classification == "reference":
                reference_ok += 1
        elif status == "failed":
            failed += 1
            if len(failed_items) < 5:
                failed_items.append({"path": str(path), "error": state[1], "updated_at": state[2]})
        else:
            pending += 1

    repo_docs = 0
    repo_chunks = 0
    reference_docs = 0
    reference_chunks = 0
    for row in indexed_rows:
        source_path = str(row["source_path"] or "").strip()
        if not source_path:
            continue
        classification = classify_coding_source_path(source_path, source)
        chunk_count = int(row["chunk_count"] or 0)
        if classification == "repo":
            repo_docs += 1
            repo_chunks += chunk_count
        elif classification == "reference":
            reference_docs += 1
            reference_chunks += chunk_count

    total = len(candidate_keys)
    progress_percent = round((float(ingested_ok) / float(total) * 100.0), 1) if total > 0 else 0.0
    tracked_percent = round((float(tracked) / float(total) * 100.0), 1) if total > 0 else 0.0
    progress = {
        "ok": True,
        "candidate_total": total,
        "ingested_ok": ingested_ok,
        "failed": failed,
        "pending": pending,
        "tracked_count": tracked,
        "progress_percent": progress_percent,
        "tracked_percent": tracked_percent,
        "repo_candidate_total": repo_total,
        "repo_ingested_ok": repo_ok,
        "repo_documents_indexed": repo_docs,
        "repo_chunks_indexed": repo_chunks,
        "reference_candidate_total": reference_total,
        "reference_ingested_ok": reference_ok,
        "reference_documents_indexed": reference_docs,
        "reference_chunks_indexed": reference_chunks,
        "coding_corpus_roots": [str(path) for path in get_coding_corpus_roots(source)],
        "coding_reference_roots": [str(path) for path in get_coding_reference_roots(source)],
        "failed_items": failed_items,
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
    }
    _write_progress_snapshot(progress, source)
    return progress
