from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

DB_CANDIDATES = [
    Path(r"D:\Sentinari\data\sentinari.db"),
    Path(r"D:\Sentinari\data\library_gemma.db"),
    Path(r"D:\Sentinari\data\smi_vocationalllm.db"),
    Path(__file__).resolve().parent / "data" / "sentinari.db",
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


app = FastAPI(title="Sentinari Local Gateway", version="0.1.0")
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
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        ).fetchall()
    return {"tables": [row["name"] for row in rows]}


@app.get("/api/search")
def search_documents(
    query: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=100),
) -> dict[str, Any]:
    q = f"%{query}%"
    try:
        with _connect() as conn:
            tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "documents" in tables:
                rows = conn.execute(
                    """
                    SELECT id, title, scientific_field, source_path
                    FROM documents
                    WHERE title LIKE ? OR source_path LIKE ? OR scientific_field LIKE ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (q, q, q, limit),
                ).fetchall()
                return {"query": query, "results": [dict(r) for r in rows]}

            # Generic fallback: search the first tables with text-ish columns
            candidates = []
            for table in sorted(tables):
                cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                names = [c[1] for c in cols]
                for col in names:
                    if any(token in col.lower() for token in ["title", "name", "content", "text", "field", "path", "source"]):
                        candidates.append((table, col))
            for table, col in candidates[:10]:
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
                            "results": [dict(r) for r in rows],
                        }
                except sqlite3.DatabaseError:
                    continue

            raise HTTPException(status_code=404, detail=f"No searchable documents found for query: {query}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/keywords")
def keyword_lookup(
    term: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    q = f"%{term}%"
    try:
        with _connect() as conn:
            if "documents" in {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                rows = conn.execute(
                    """
                    SELECT id, title, scientific_field, source_path
                    FROM documents
                    WHERE title LIKE ? OR scientific_field LIKE ? OR source_path LIKE ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (q, q, q, limit),
                ).fetchall()
                return {"term": term, "results": [dict(r) for r in rows]}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"term": term, "results": []}


@app.get("/api/documents/{document_id}")
def document_by_id(document_id: int) -> dict[str, Any]:
    try:
        with _connect() as conn:
            if "documents" in {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                row = conn.execute(
                    "SELECT * FROM documents WHERE id = ?",
                    (document_id,),
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
                return dict(row)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    raise HTTPException(status_code=404, detail=f"Document {document_id} not found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("gateway_local:app", host="0.0.0.0", port=8000, reload=False)
