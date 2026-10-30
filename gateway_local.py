# gateway_local.py
from __future__ import annotations

import sqlite3
from pathlib import Path
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

DB_CANDIDATES = [
    Path(r"D:\Sentinari\data\sentinari.db"),
    Path(r"D:\Sentinari\data\library_gemma.db"),
    Path(r"D:\Sentinari\data\smi_vocationalllm.db"),
    Path.cwd() / "data" / "sentinari.db",
    Path.cwd() / "data" / "library_gemma.db",
    Path.cwd() / "data" / "smi_vocationalllm.db",
]

def find_db() -> Path:
    for p in DB_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError("No SQLite DB found")

def connect():
    db = find_db()
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn

app = FastAPI(title="Sentinari Local Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    return {"ok": True, "db": str(find_db())}

@app.get("/api/tables")
def tables():
    with connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        ).fetchall()
    return {"tables": [r["name"] for r in rows]}

@app.get("/api/search")
def search(query: str = Query(...), limit: int = 10):
    q = f"%{query}%"
    with connect() as conn:
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
            return {"results": [dict(r) for r in rows]}
    raise HTTPException(status_code=404, detail="No matching document table found")

@app.get("/api/keywords")
def keywords(term: str = Query(...), limit: int = 20):
    q = f"%{term}%"
    with connect() as conn:
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
            return {"results": [dict(r) for r in rows]}
    return {"results": []}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)