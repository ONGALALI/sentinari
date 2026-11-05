from __future__ import annotations

import sqlite3
from pathlib import Path

DB_CANDIDATES = [
    Path(r"D:\\Sentinari\\data\\sentinari.db"),
    Path(r"D:\\Sentinari\\data\\library_gemma.db"),
    Path(r"D:\\Sentinari\\data\\smi_vocationalllm.db"),
    Path.cwd() / "data" / "sentinari.db",
    Path.cwd() / "data" / "library_gemma.db",
    Path.cwd() / "data" / "smi_vocationalllm.db",
]


def find_db() -> Path:
    for p in DB_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(
        "No SQLite database found. Checked: " + ", ".join(str(p) for p in DB_CANDIDATES)
    )


def table_info(conn: sqlite3.Connection, table: str):
    cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return cols


def main() -> None:
    db_path = find_db()
    print(f"Inspecting database: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        ).fetchall()
        print(f"Tables ({len(tables)}):")
        for row in tables:
            table = row["name"]
            print(f"\n## {table}")
            cols = table_info(conn, table)
            if not cols:
                print("  (no columns returned)")
                continue
            for c in cols:
                cid, name, dtype, notnull, default_value, pk = c
                print(f"  - {name}: {dtype} (notnull={notnull}, pk={pk})")

        print("\nSearching for likely text-bearing tables...")
        for row in tables:
            table = row["name"]
            cols = table_info(conn, table)
            names = [c[1] for c in cols]
            text_like = [n for n in names if any(token in n.lower() for token in ["title", "name", "content", "text", "body", "field", "path", "source", "keyword", "description"]) ]
            if text_like:
                print(f"  {table}: text-like columns -> {', '.join(text_like[:8])}")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        print(exc)
        raise SystemExit(1)
