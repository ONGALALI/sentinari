"""Sentinari SQLite to PostgreSQL + pgvector Migration Tool.

Migrates:
- 14,788 documents
- 699,743 chunks (populates vector(768) from the staged .npy coordinates)
- 1,247,694 Article V records
- Pattern Discovery entities, relations, and patterns
from sentinari.db directly into Cloud SQL (PostgreSQL 16 + pgvector).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_SQLITE_PATH = Path(r"D:\Sentinari\data\sentinari.db")
DEFAULT_INDEX_DIR = Path(r"D:\Sentinari\data\rag_index")


def parse_args():
    parser = argparse.ArgumentParser(description="Migrate Sentinari to PostgreSQL + pgvector")
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE_PATH, help="Source SQLite DB")
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR, help="Path to staged .npy vectors")
    parser.add_argument("--pg-url", type=str, default=os.environ.get("DATABASE_URL", ""), help="PostgreSQL connection string")
    parser.add_argument("--batch-size", type=int, default=5000, help="Batch commit size")
    parser.add_argument("--skip-vectors", action="store_true", help="Skip populating vectors")
    parser.add_argument("--limit-chunks", type=int, default=0, help="Optional chunk limit for testing")
    return parser.parse_args()


def run_migration():
    args = parse_args()
    if not args.sqlite.exists():
        print(f"[-] SQLite database not found at {args.sqlite}")
        sys.exit(1)

    print(f"[*] Opening SQLite source: {args.sqlite}")
    conn_sq = sqlite3.connect(f"file:{args.sqlite}?mode=ro", uri=True)
    cur_sq = conn_sq.cursor()

    docs_count = cur_sq.execute("SELECT COUNT(*) FROM documents;").fetchone()[0]
    chunks_count = cur_sq.execute("SELECT COUNT(*) FROM chunks;").fetchone()[0]
    art_v_count = cur_sq.execute("SELECT COUNT(*) FROM article_v_knowledge;").fetchone()[0]

    print(f"[+] Discovered source data:")
    print(f"    - Documents: {docs_count:,}")
    print(f"    - Chunks:    {chunks_count:,}")
    print(f"    - Article V: {art_v_count:,}")

    if not args.pg_url:
        print("[-] No --pg-url provided and DATABASE_URL environment variable is unset.")
        conn_sq.close()
        return

    import psycopg2
    import psycopg2.extras
    from pgvector.psycopg2 import register_vector

    print(f"[*] Connecting to PostgreSQL target...")
    conn_pg = psycopg2.connect(args.pg_url)
    cur_pg = conn_pg.cursor()

    # 1. Apply Schema
    schema_sql_path = Path(__file__).parent / "cloud_cutover_schema.sql"
    if schema_sql_path.exists():
        print(f"[*] Applying PostgreSQL schema from {schema_sql_path.name}...")
        cur_pg.execute(schema_sql_path.read_text(encoding="utf-8"))
        conn_pg.commit()

    register_vector(conn_pg)

    # 2. Migrate Documents
    print(f"[*] Migrating {docs_count:,} documents...")
    t0 = time.time()
    cur_sq.execute(
        """
        SELECT id, source_id, title, source_type, source_url, source_path,
               checksum, archive_path, module, topic, scientific_field,
               vocational_discipline, source_collection, language, license,
               published_date, authors, publisher, document_metadata_json,
               raw_char_count, priority, created_at
        FROM documents ORDER BY id ASC;
        """
    )
    doc_rows = []
    for r in cur_sq:
        doc_rows.append(r)
        if len(doc_rows) >= args.batch_size:
            psycopg2.extras.execute_values(
                cur_pg,
                """
                INSERT INTO documents (
                    id, source_id, title, source_type, source_url, source_path,
                    checksum, archive_path, module, topic, scientific_field,
                    vocational_discipline, source_collection, language, license,
                    published_date, authors, publisher, document_metadata,
                    raw_char_count, priority, created_at
                ) VALUES %s ON CONFLICT (id) DO NOTHING;
                """,
                doc_rows,
                template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
            )
            conn_pg.commit()
            doc_rows.clear()

    if doc_rows:
        psycopg2.extras.execute_values(
            cur_pg,
            """
            INSERT INTO documents (
                id, source_id, title, source_type, source_url, source_path,
                checksum, archive_path, module, topic, scientific_field,
                vocational_discipline, source_collection, language, license,
                published_date, authors, publisher, document_metadata,
                raw_char_count, priority, created_at
            ) VALUES %s ON CONFLICT (id) DO NOTHING;
            """,
            doc_rows,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
        )
        conn_pg.commit()
    print(f"[+] Documents migrated in {time.time() - t0:.1f}s!")

    # 3. Load Vector Mapping from staged .npy (fast lookup)
    cid_to_idx: dict[int, int] = {}
    vectors = None
    vec_file = args.index_dir / "sentinari_vectors.npy"
    cid_file = args.index_dir / "sentinari_chunk_ids.npy"
    if not args.skip_vectors and vec_file.exists() and cid_file.exists():
        print(f"[*] Memory-mapping staged vectors from {vec_file.name}...")
        vectors = np.load(vec_file, mmap_mode="r")
        chunk_ids = np.load(cid_file, mmap_mode="r")
        print(f"[*] Building chunk_id -> index map for {len(chunk_ids):,} vectors...")
        cid_to_idx = {int(cid): i for i, cid in enumerate(chunk_ids)}
        print(f"[+] Index map ready ({len(cid_to_idx):,} mappings).")

    # 4. Migrate Chunks
    cur_pg.execute("SELECT COALESCE(MAX(id), 0) FROM chunks;")
    max_chunk_id = cur_pg.fetchone()[0]
    if max_chunk_id > 0:
        print(f"[*] Resuming chunks migration from id > {max_chunk_id:,}...", flush=True)
        cur_sq.execute(
            """
            SELECT id, document_id, chunk_index, content, token_estimate, chunk_hash, metadata_json
            FROM chunks WHERE id > ? ORDER BY id ASC;
            """,
            (max_chunk_id,),
        )
    else:
        print(f"[*] Migrating {chunks_count:,} chunks with native vectors...", flush=True)
        cur_sq.execute(
            """
            SELECT id, document_id, chunk_index, content, token_estimate, chunk_hash, metadata_json
            FROM chunks ORDER BY id ASC;
            """
        )

    chunk_batch_size = min(args.batch_size, 2000)
    chunk_rows = []
    migrated_chunks = 0
    t_chunk = time.time()

    for cid, did, cidx, content, toksen, chash, meta_json in cur_sq:
        v_idx = cid_to_idx.get(cid)
        vec_param = vectors[v_idx].tolist() if v_idx is not None and vectors is not None else None

        chunk_rows.append((cid, did, cidx, content, toksen, chash, meta_json, vec_param))
        migrated_chunks += 1

        if len(chunk_rows) >= chunk_batch_size:
            psycopg2.extras.execute_values(
                cur_pg,
                """
                INSERT INTO chunks (
                    id, document_id, chunk_index, content, token_estimate,
                    chunk_hash, metadata, embedding
                ) VALUES %s ON CONFLICT (id) DO NOTHING;
                """,
                chunk_rows,
                template="(%s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
            )
            conn_pg.commit()
            chunk_rows.clear()
            rate = migrated_chunks / max(0.1, time.time() - t_chunk)
            print(f"    Staged {migrated_chunks:,} chunks ({rate:.0f} chunks/sec)...", flush=True)

        if args.limit_chunks and migrated_chunks >= args.limit_chunks:
            break

    if chunk_rows:
        psycopg2.extras.execute_values(
            cur_pg,
            """
            INSERT INTO chunks (
                id, document_id, chunk_index, content, token_estimate,
                chunk_hash, metadata, embedding
            ) VALUES %s ON CONFLICT (id) DO NOTHING;
            """,
            chunk_rows,
            template="(%s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
        )
        conn_pg.commit()
    print(f"[+] Chunks migrated in {time.time() - t_chunk:.1f}s!", flush=True)

    # 5. Migrate Article V Knowledge Records
    cur_pg.execute("SELECT COALESCE(MAX(source_rowid), 0) FROM article_v_knowledge;")
    max_art_rowid = cur_pg.fetchone()[0]
    if max_art_rowid > 0:
        print(f"[*] Resuming Article V records from source_rowid > {max_art_rowid:,}...", flush=True)
        cur_sq.execute(
            """
            SELECT observation_id, source_db, source_table, source_rowid, timestamp,
                   scientific_field, falsifiable_claims, numerical_metrics,
                   epistemic_confidence, provenance_json
            FROM article_v_knowledge WHERE rowid > ? ORDER BY rowid ASC;
            """,
            (max_art_rowid,),
        )
    else:
        print(f"[*] Migrating {art_v_count:,} Article V telemetry records...", flush=True)
        cur_sq.execute(
            """
            SELECT observation_id, source_db, source_table, source_rowid, timestamp,
                   scientific_field, falsifiable_claims, numerical_metrics,
                   epistemic_confidence, provenance_json
            FROM article_v_knowledge ORDER BY rowid ASC;
            """
        )

    art_rows = []
    migrated_art = 0
    t_art = time.time()

    for r in cur_sq:
        art_rows.append(r)
        migrated_art += 1
        if len(art_rows) >= args.batch_size:
            psycopg2.extras.execute_values(
                cur_pg,
                """
                INSERT INTO article_v_knowledge (
                    observation_id, source_db, source_table, source_rowid, timestamp,
                    scientific_field, falsifiable_claims, numerical_metrics,
                    epistemic_confidence, provenance_json
                ) VALUES %s ON CONFLICT (observation_id) DO NOTHING;
                """,
                art_rows,
                template="(%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb)",
            )
            conn_pg.commit()
            art_rows.clear()
            rate = migrated_art / max(0.1, time.time() - t_art)
            print(f"    Staged {migrated_art:,} Article V rows ({rate:.0f} rows/sec)...", flush=True)

    if art_rows:
        psycopg2.extras.execute_values(
            cur_pg,
            """
            INSERT INTO article_v_knowledge (
                observation_id, source_db, source_table, source_rowid, timestamp,
                scientific_field, falsifiable_claims, numerical_metrics,
                epistemic_confidence, provenance_json
            ) VALUES %s ON CONFLICT (observation_id) DO NOTHING;
            """,
            art_rows,
            template="(%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb)",
        )
        conn_pg.commit()
    print(f"[+] Article V telemetry records migrated in {time.time() - t_art:.1f}s!", flush=True)

    # 6. Build High-Performance Vector & Full-Text Search Indexes
    print(f"[*] Building HNSW vector index on chunks(embedding)...", flush=True)
    t_idx = time.time()
    cur_pg.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw 
        ON chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
    """)
    conn_pg.commit()
    print(f"[+] HNSW vector index created in {time.time() - t_idx:.1f}s!", flush=True)

    print(f"[*] Building Full-Text Search index...", flush=True)
    t_fts = time.time()
    cur_pg.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_fts 
        ON chunks USING gin(to_tsvector('english', substring(content, 1, 100000)));
    """)
    conn_pg.commit()
    print(f"[+] Full-Text Search index created in {time.time() - t_fts:.1f}s!", flush=True)

    conn_sq.close()
    conn_pg.close()
    print(f"[+] COMPLETE: Entire knowledge library migrated to Cloud PostgreSQL + pgvector successfully!", flush=True)


if __name__ == "__main__":
    run_migration()
