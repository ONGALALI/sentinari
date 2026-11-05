from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

DB_CANDIDATES = [
    Path(r"D:\Sentinari\data\sentinari.db"),
    Path(r"D:\Sentinari\data\library_gemma.db"),
    Path(r"D:\Sentinari\data\smi_vocationalllm.db"),
    Path.cwd() / "data" / "sentinari.db",
    Path.cwd() / "data" / "library_gemma.db",
    Path.cwd() / "data" / "smi_vocationalllm.db",
    Path(__file__).resolve().parent / "data" / "sentinari.db",
    Path(__file__).resolve().parent / "data" / "library_gemma.db",
    Path(__file__).resolve().parent / "data" / "smi_vocationalllm.db",
]


def _find_db() -> Path:
    for p in DB_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(
        "No Sentinari library database was found. "
        "Expected one of: D:\\Sentinari\\data\\sentinari.db, "
        "D:\\Sentinari\\data\\library_gemma.db, or the repo-local data folder."
    )


def _connect() -> sqlite3.Connection:
    db_path = _find_db()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _safe_json(value: str | None) -> Any:
    if value in (None, ""):
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


app = FastAPI(title="Sentinari Local Gateway", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    db_path = _find_db()
    return {
        "ok": True,
        "db": str(db_path),
        "exists": db_path.exists(),
        "project": "Sentinari",
        "mode": "local-machine-gateway",
    }


@app.get("/api/tables")
def list_tables() -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        ).fetchall()
    return {"tables": [row["name"] for row in rows]}


@app.get("/api/fields")
def list_fields(limit: int = Query(200, ge=1, le=500)) -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT scientific_field
            FROM documents
            WHERE scientific_field IS NOT NULL AND trim(scientific_field) != ''
            ORDER BY scientific_field
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {"fields": [row["scientific_field"] for row in rows]}


@app.get("/api/search")
def search_documents(
    query: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=100),
) -> dict[str, Any]:
    q = f"%{query}%"
    try:
        with _connect() as conn:
            tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

            if "documents" in tables:
                rows = conn.execute(
                    """
                    SELECT id, title, scientific_field, source_path, source_url, domain, topic,
                           source_collection, published_date, authors, publisher
                    FROM documents
                    WHERE title LIKE ?
                       OR source_path LIKE ?
                       OR scientific_field LIKE ?
                       OR domain LIKE ?
                       OR topic LIKE ?
                       OR source_collection LIKE ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (q, q, q, q, q, q, limit),
                ).fetchall()
                return {
                    "query": query,
                    "count": len(rows),
                    "results": [dict(r) for r in rows],
                }

            # Fallback: generic search across text-ish columns in any table
            candidates: list[tuple[str, str]] = []
            for table in sorted(tables):
                try:
                    cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                except sqlite3.DatabaseError:
                    continue
                for col in cols:
                    name = str(col[1]).lower()
                    if any(token in name for token in ["title", "name", "content", "text", "field", "path", "source", "topic", "domain"]):
                        candidates.append((table, str(col[1])))

            for table, col in candidates[:20]:
                try:
                    rows = conn.execute(
                        f'SELECT * FROM "{table}" WHERE "{col}" LIKE ? LIMIT ?',
                        (q, limit),
                    ).fetchall()
                    if rows:
                        return {
                            "query": query,
                            "table": table,
                            "column": col,
                            "count": len(rows),
                            "results": [dict(r) for r in rows],
                        }
                except sqlite3.DatabaseError:
                    continue

            raise HTTPException(status_code=404, detail=f"No searchable documents found for query: {query}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/documents/{document_id}")
def document_by_id(document_id: int) -> dict[str, Any]:
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

            payload = dict(row)
            payload["document_metadata_json"] = _safe_json(payload.get("document_metadata_json"))
            return {"document": payload}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/chunks/{document_id}")
def chunks_by_document(document_id: int, limit: int = Query(200, ge=1, le=500)) -> dict[str, Any]:
    try:
        with _connect() as conn:
            if "chunks" not in {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}:
                raise HTTPException(status_code=404, detail=f"No chunk table found for document {document_id}")

            rows = conn.execute(
                """
                SELECT id, document_id, chunk_index, content, token_estimate, metadata_json, created_at, chunk_hash
                FROM chunks
                WHERE document_id = ?
                ORDER BY chunk_index ASC
                LIMIT ?
                """,
                (document_id, limit),
            ).fetchall()

            return {
                "document_id": document_id,
                "count": len(rows),
                "chunks": [
                    {
                        **dict(r),
                        "metadata_json": _safe_json(r["metadata_json"]),
                    }
                    for r in rows
                ],
            }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/recent")
def recent_documents(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    try:
        with _connect() as conn:
            if "documents" not in {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}:
                return {"results": []}

            rows = conn.execute(
                """
                SELECT id, title, scientific_field, source_path, created_at
                FROM documents
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return {"count": len(rows), "results": [dict(r) for r in rows]}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("gateway_local:app", host="0.0.0.0", port=8000, reload=False)
