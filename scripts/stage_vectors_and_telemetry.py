"""Sentinari High-Performance Vector Staging & Article V Telemetry Pipeline.

Stages 768-d embeddings from SQLite (which took ~7 GB of JSON string bloat)
into memory-mapped NumPy binary arrays (.npy).
Enables sub-50ms vector searches without SQLite read/write lock contention.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_DB_PATH = Path(r"D:\Sentinari\data\sentinari.db")
DEFAULT_INDEX_DIR = Path(r"D:\Sentinari\data\rag_index")

_NUMBER_RE = re.compile(
    r"[-+]?\d+(?:\.\d+)?(?:\s*(?:%|percent|kg|km|ms|s|GHz|MHz|MB|GB|K|°C|mol))?",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.\!\?])\s+")


def stage_vectors_to_numpy(
    db_path: Path = DEFAULT_DB_PATH,
    output_dir: Path = DEFAULT_INDEX_DIR,
    batch_size: int = 10_000,
) -> dict[str, Any]:
    """Extracts all stored embeddings from SQLite into binary .npy coordinate arrays."""
    output_dir.mkdir(parents=True, exist_ok=True)
    npy_vectors_path = output_dir / "sentinari_vectors.npy"
    npy_chunk_ids_path = output_dir / "sentinari_chunk_ids.npy"
    npy_doc_ids_path = output_dir / "sentinari_doc_ids.npy"
    manifest_path = output_dir / "index_manifest.json"

    print(f"[*] Opening {db_path} in read-only mode...")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()

    count_query = (
        "SELECT COUNT(*) FROM chunks WHERE embedding_json IS NOT NULL AND length(embedding_json) > 10;"
    )
    total_embedded = cur.execute(count_query).fetchone()[0]
    print(f"[+] Total embedded chunks found: {total_embedded:,}")

    if total_embedded == 0:
        print("[-] No embeddings found to stage.")
        conn.close()
        return {"total_embedded": 0}

    # Preallocate NumPy arrays to keep memory flat (~1.37 GB total)
    vector_dim = 768
    print(f"[*] Preallocating float32 array: shape=({total_embedded:,}, {vector_dim})...")
    vectors = np.zeros((total_embedded, vector_dim), dtype=np.float32)
    chunk_ids = np.zeros(total_embedded, dtype=np.int64)
    doc_ids = np.zeros(total_embedded, dtype=np.int64)

    cursor = conn.execute(
        """
        SELECT id, document_id, embedding_json
        FROM chunks
        WHERE embedding_json IS NOT NULL AND length(embedding_json) > 10
        ORDER BY id ASC;
        """
    )

    t0 = time.time()
    idx = 0
    batch_vectors = []
    batch_cids = []
    batch_dids = []

    print("[*] Streaming vector rows and parsing...")
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break

        for cid, did, emb_json in rows:
            try:
                emb = json.loads(emb_json)
                if isinstance(emb, list) and len(emb) == vector_dim:
                    batch_vectors.append(emb)
                    batch_cids.append(cid)
                    batch_dids.append(did)
            except Exception:
                continue

        batch_count = len(batch_vectors)
        if batch_count > 0:
            end_idx = idx + batch_count
            vectors[idx:end_idx] = np.array(batch_vectors, dtype=np.float32)
            chunk_ids[idx:end_idx] = np.array(batch_cids, dtype=np.int64)
            doc_ids[idx:end_idx] = np.array(batch_dids, dtype=np.int64)
            idx = end_idx
            batch_vectors.clear()
            batch_cids.clear()
            batch_dids.clear()

        elapsed = time.time() - t0
        rate = idx / max(0.1, elapsed)
        print(f"    Staged {idx:,} / {total_embedded:,} vectors ({rate:.0f} vecs/sec)...")

    conn.close()

    # Trim if any rows were skipped
    if idx < total_embedded:
        vectors = vectors[:idx]
        chunk_ids = chunk_ids[:idx]
        doc_ids = doc_ids[:idx]

    print(f"[*] Saving arrays to {output_dir}...")
    np.save(npy_vectors_path, vectors)
    np.save(npy_chunk_ids_path, chunk_ids)
    np.save(npy_doc_ids_path, doc_ids)

    total_time = time.time() - t0
    vec_size_mb = npy_vectors_path.stat().st_size / (1024 * 1024)

    manifest = {
        "staged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_db": str(db_path),
        "total_vectors": int(idx),
        "vector_dim": vector_dim,
        "dtype": "float32",
        "vectors_file": npy_vectors_path.name,
        "chunk_ids_file": npy_chunk_ids_path.name,
        "doc_ids_file": npy_doc_ids_path.name,
        "vectors_size_mb": round(vec_size_mb, 2),
        "staging_duration_seconds": round(total_time, 2),
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"[+] Vector staging complete!")
    print(f"    Total vectors: {idx:,}")
    print(f"    Vector array size: {vec_size_mb:.1f} MB (vs ~6.6 GB SQLite JSON bloat)")
    print(f"    Duration: {total_time:.1f}s")
    print(f"    Saved manifest to: {manifest_path}")

    return manifest


def verify_fast_query(output_dir: Path = DEFAULT_INDEX_DIR, top_k: int = 5) -> None:
    """Benchmark raw vector search latency using the staged .npy array."""
    manifest_path = output_dir / "index_manifest.json"
    if not manifest_path.exists():
        print("[-] Manifest not found. Run staging first.")
        return

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    vectors_path = output_dir / manifest["vectors_file"]
    cids_path = output_dir / manifest["chunk_ids_file"]

    print("[*] Memory-mapping vectors for benchmark test...")
    t0 = time.time()
    # Memory-mapped read: zero memory copy overhead!
    vectors = np.load(vectors_path, mmap_mode="r")
    cids = np.load(cids_path, mmap_mode="r")
    load_time = (time.time() - t0) * 1000

    print(f"[+] Memory-mapped {vectors.shape[0]:,} vectors ({manifest['vector_dim']}d) in {load_time:.2f} ms")

    # Generate a sample query vector (normalized)
    np.random.seed(42)
    sample_query = np.random.randn(manifest["vector_dim"]).astype(np.float32)
    sample_query /= np.linalg.norm(sample_query)

    print("[*] Executing matrix dot-product similarity search over all vectors...")
    t_search = time.time()
    # Compute norms once (or assume normalized)
    norms = np.linalg.norm(vectors, axis=1)
    norms[norms == 0] = 1.0
    scores = np.dot(vectors, sample_query) / norms
    top_indices = np.argpartition(scores, -top_k)[-top_k:]
    top_indices = top_indices[np.argsort(-scores[top_indices])]
    search_time = (time.time() - t_search) * 1000

    print(f"[+] Search completed across {len(scores):,} vectors in {search_time:.2f} ms!")
    print(f"    Top {top_k} chunk IDs and scores:")
    for rank, idx in enumerate(top_indices, 1):
        print(f"      #{rank}: Chunk ID {cids[idx]} | Cosine Score: {scores[idx]:.4f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage Sentinari Vectors to NumPy")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--benchmark", action="store_true", help="Run search benchmark")
    args = parser.parse_args()

    if args.benchmark:
        verify_fast_query(args.out)
    else:
        stage_vectors_to_numpy(args.db, args.out)
        verify_fast_query(args.out)
