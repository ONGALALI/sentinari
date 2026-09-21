from __future__ import annotations

import json
import math
import random
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .config import get_settings


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}")
STOP_WORDS = {
    "about",
    "after",
    "again",
    "against",
    "also",
    "among",
    "because",
    "been",
    "being",
    "between",
    "both",
    "can",
    "could",
    "does",
    "each",
    "from",
    "have",
    "into",
    "its",
    "many",
    "more",
    "most",
    "other",
    "over",
    "same",
    "such",
    "than",
    "that",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "under",
    "using",
    "very",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
    "your",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_float_vector(raw: Any) -> list[float] | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    out: list[float] = []
    for item in parsed:
        try:
            out.append(float(item))
        except Exception:
            return None
    return out if out else None


def _normalize_vector(v: list[float]) -> list[float]:
    if not v:
        return v
    norm = math.sqrt(sum(x * x for x in v))
    if norm <= 0:
        return [0.0 for _ in v]
    return [x / norm for x in v]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def _mean_vector(vectors: list[list[float]], width: int) -> list[float]:
    if not vectors:
        return [0.0] * width
    sums = [0.0] * width
    for v in vectors:
        for i in range(width):
            sums[i] += v[i]
    return _normalize_vector([x / len(vectors) for x in sums])


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN_RE.finditer(text or ""):
        token = match.group(0).lower()
        if token in STOP_WORDS:
            continue
        if token.isdigit():
            continue
        tokens.append(token)
    return tokens


def _build_lexical_vectors(texts: list[str], max_features: int) -> tuple[list[list[float]], list[str]]:
    doc_counts: list[Counter[str]] = []
    document_frequency: Counter[str] = Counter()
    term_frequency: Counter[str] = Counter()

    for text in texts:
        counts = Counter(_tokenize(text))
        doc_counts.append(counts)
        term_frequency.update(counts)
        for token in counts.keys():
            document_frequency[token] += 1

    min_df = max(2, int(len(texts) * 0.01))
    candidates = [
        token
        for token, _ in term_frequency.most_common(max_features * 4)
        if document_frequency[token] >= min_df
    ]
    vocab = candidates[: max(32, max_features)]
    if not vocab:
        return [], []

    vocab_index = {token: idx for idx, token in enumerate(vocab)}
    vectors: list[list[float]] = []
    for counts in doc_counts:
        vec = [0.0] * len(vocab)
        for token, count in counts.items():
            idx = vocab_index.get(token)
            if idx is None:
                continue
            vec[idx] = float(count)
        vectors.append(_normalize_vector(vec))

    return vectors, vocab


def _resolve_k(
    n_vectors: int,
    requested_clusters: int | None,
    target_cluster_size: int,
    max_clusters: int,
) -> int:
    if n_vectors <= 0:
        return 0

    if requested_clusters is not None and requested_clusters > 0:
        k = requested_clusters
    else:
        k = max(1, int(round(float(n_vectors) / max(1, target_cluster_size))))
        if n_vectors >= max(12, target_cluster_size) and k < 2:
            k = 2

    k = max(1, min(int(k), int(max_clusters), n_vectors))
    return k


def _init_centroids_kmeanspp(vectors: list[list[float]], k: int, rng: random.Random) -> list[list[float]]:
    if k <= 0:
        return []
    if k >= len(vectors):
        return [v[:] for v in vectors]

    chosen: list[int] = [rng.randrange(0, len(vectors))]
    while len(chosen) < k:
        distances: list[float] = []
        for idx, vec in enumerate(vectors):
            if idx in chosen:
                distances.append(0.0)
                continue
            nearest = max(_cosine_similarity(vec, vectors[c]) for c in chosen)
            # cosine distance in [0..2] once normalized
            distances.append(max(0.0, 1.0 - nearest))

        total = sum(distances)
        if total <= 0:
            for idx in range(len(vectors)):
                if idx not in chosen:
                    chosen.append(idx)
                if len(chosen) >= k:
                    break
            break

        threshold = rng.random() * total
        cumulative = 0.0
        selected = None
        for idx, dist in enumerate(distances):
            cumulative += dist
            if cumulative >= threshold:
                selected = idx
                break
        if selected is None:
            selected = len(vectors) - 1
        if selected in chosen:
            for idx in range(len(vectors)):
                if idx not in chosen:
                    selected = idx
                    break
        chosen.append(selected)

    return [vectors[idx][:] for idx in chosen[:k]]


def _kmeans_cosine(
    vectors: list[list[float]],
    k: int,
    max_iterations: int,
    random_seed: int,
) -> tuple[list[int], list[list[float]], int]:
    if not vectors:
        return [], [], 0
    if k <= 1:
        centroid = _mean_vector(vectors, len(vectors[0]))
        return [0 for _ in vectors], [centroid], 1

    rng = random.Random(int(random_seed))
    centroids = _init_centroids_kmeanspp(vectors, k, rng)
    if not centroids:
        centroids = [vectors[0][:]]
        k = 1

    assignments = [-1] * len(vectors)
    iterations = 0
    width = len(vectors[0])

    for i in range(max(1, int(max_iterations))):
        iterations = i + 1
        changed = False

        for idx, vec in enumerate(vectors):
            best_cluster = 0
            best_score = -2.0
            for cluster_idx, centroid in enumerate(centroids):
                score = _cosine_similarity(vec, centroid)
                if score > best_score:
                    best_score = score
                    best_cluster = cluster_idx
            if assignments[idx] != best_cluster:
                assignments[idx] = best_cluster
                changed = True

        grouped: list[list[list[float]]] = [[] for _ in range(len(centroids))]
        for idx, cluster_idx in enumerate(assignments):
            if cluster_idx < 0 or cluster_idx >= len(grouped):
                continue
            grouped[cluster_idx].append(vectors[idx])

        new_centroids: list[list[float]] = []
        for cluster_idx, members in enumerate(grouped):
            if members:
                new_centroids.append(_mean_vector(members, width))
                continue
            # Recover empty clusters by reseeding from random vector.
            new_centroids.append(vectors[rng.randrange(0, len(vectors))][:])
            changed = True

        centroids = new_centroids
        if not changed:
            break

    return assignments, centroids, iterations


def _cluster_terms(texts: list[str], max_terms: int) -> list[str]:
    counter: Counter[str] = Counter()
    for text in texts:
        counter.update(_tokenize(text))
    return [token for token, _ in counter.most_common(max(1, int(max_terms)))]


def _build_cluster_label(cluster_index: int, top_terms: list[str]) -> str:
    if not top_terms:
        return f"Cluster {cluster_index + 1}"
    return ", ".join(top_terms[:3])


def _run_settings() -> dict[str, Any]:
    raw = get_settings().get("unsupervised", {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "min_chunks_for_clustering": max(4, int(raw.get("min_chunks_for_clustering") or 24)),
        "target_cluster_size": max(8, int(raw.get("target_cluster_size") or 40)),
        "max_clusters": max(2, int(raw.get("max_clusters") or 18)),
        "max_iterations": max(2, int(raw.get("max_iterations") or 25)),
        "max_terms_per_cluster": max(3, int(raw.get("max_terms_per_cluster") or 8)),
        "lexical_max_features": max(64, int(raw.get("lexical_max_features") or 512)),
        "random_seed": int(raw.get("random_seed") or 42),
    }


def rebuild_unsupervised_clusters(
    conn: sqlite3.Connection,
    *,
    requested_clusters: int | None = None,
    scientific_field: str | None = None,
    vocational_discipline: str | None = None,
    source_collection: str | None = None,
    min_chunks: int | None = None,
    max_terms_per_cluster: int | None = None,
    force_lexical: bool = False,
) -> dict[str, Any]:
    cfg = _run_settings()
    if not cfg["enabled"]:
        return {"ok": False, "error": "Unsupervised clustering is disabled in config.unsupervised.enabled."}

    minimum = max(4, int(min_chunks if min_chunks is not None else cfg["min_chunks_for_clustering"]))
    max_terms = max(
        3,
        int(max_terms_per_cluster if max_terms_per_cluster is not None else cfg["max_terms_per_cluster"]),
    )
    started_at = _utc_now_iso()
    run_insert = conn.execute(
        """
        INSERT INTO unsupervised_runs (
            algorithm,
            vector_source,
            requested_clusters,
            scientific_field,
            vocational_discipline,
            source_collection,
            started_at,
            notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            "kmeans-cosine",
            "pending",
            requested_clusters,
            (scientific_field or "").strip() or None,
            (vocational_discipline or "").strip() or None,
            (source_collection or "").strip() or None,
            started_at,
            "run started",
        ),
    )
    run_id = int(run_insert.lastrowid)

    sql = """
    SELECT
        c.id AS chunk_id,
        c.content AS content,
        c.embedding_json AS embedding_json,
        d.source_id AS source_id,
        d.title AS title,
        d.scientific_field AS scientific_field,
        d.vocational_discipline AS vocational_discipline,
        d.source_collection AS source_collection
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE IFNULL(TRIM(c.content), '') <> ''
    """
    args: list[Any] = []
    if scientific_field:
        sql += " AND IFNULL(d.scientific_field, '') = ?"
        args.append(scientific_field.strip())
    if vocational_discipline:
        sql += " AND IFNULL(d.vocational_discipline, '') = ?"
        args.append(vocational_discipline.strip())
    if source_collection:
        sql += " AND IFNULL(d.source_collection, '') = ?"
        args.append(source_collection.strip())
    sql += " ORDER BY c.id ASC"

    raw_rows = [dict(row) for row in conn.execute(sql, tuple(args)).fetchall()]
    if not raw_rows:
        completed_at = _utc_now_iso()
        conn.execute(
            """
            UPDATE unsupervised_runs
            SET vector_source = ?, resolved_clusters = ?, min_points = ?, chunk_count = ?, completed_at = ?, notes = ?
            WHERE id = ?;
            """,
            ("none", 0, minimum, 0, completed_at, "No eligible chunks were found for this filter scope.", run_id),
        )
        return {
            "ok": True,
            "run_id": run_id,
            "status": "skipped",
            "message": "No eligible chunks were found for this filter scope.",
            "chunk_count": 0,
            "clusters": [],
        }

    embedding_dim_counts: Counter[int] = Counter()
    embedded_rows: list[dict[str, Any]] = []
    for row in raw_rows:
        vector = _to_float_vector(row.get("embedding_json"))
        if not vector:
            continue
        embedding_dim_counts[len(vector)] += 1
        row_copy = dict(row)
        row_copy["vector"] = _normalize_vector(vector)
        embedded_rows.append(row_copy)

    rows: list[dict[str, Any]]
    vectors: list[list[float]]
    vector_source = "lexical"

    if not force_lexical and embedded_rows and embedding_dim_counts:
        dominant_dim = embedding_dim_counts.most_common(1)[0][0]
        filtered = [r for r in embedded_rows if len(r["vector"]) == dominant_dim]
        if len(filtered) >= minimum:
            rows = filtered
            vectors = [r["vector"] for r in filtered]
            vector_source = "embedding"
        else:
            rows = raw_rows
            lexical_vectors, _ = _build_lexical_vectors(
                [str(r.get("content") or "") for r in rows],
                max_features=cfg["lexical_max_features"],
            )
            vectors = lexical_vectors
    else:
        rows = raw_rows
        lexical_vectors, _ = _build_lexical_vectors(
            [str(r.get("content") or "") for r in rows],
            max_features=cfg["lexical_max_features"],
        )
        vectors = lexical_vectors

    usable_rows: list[dict[str, Any]] = []
    usable_vectors: list[list[float]] = []
    for idx, vec in enumerate(vectors):
        if not vec or len(vec) == 0:
            continue
        if all(abs(v) < 1e-12 for v in vec):
            continue
        usable_rows.append(rows[idx])
        usable_vectors.append(vec)

    if len(usable_rows) < minimum:
        completed_at = _utc_now_iso()
        message = (
            f"Not enough chunks for clustering (need >= {minimum}, got {len(usable_rows)}). "
            "Add more PDF content or lower min_chunks in request/config."
        )
        conn.execute(
            """
            UPDATE unsupervised_runs
            SET vector_source = ?, resolved_clusters = ?, min_points = ?, chunk_count = ?, completed_at = ?, notes = ?
            WHERE id = ?;
            """,
            (vector_source, 0, minimum, len(usable_rows), completed_at, message, run_id),
        )
        return {
            "ok": True,
            "run_id": run_id,
            "status": "skipped",
            "message": message,
            "vector_source": vector_source,
            "chunk_count": len(usable_rows),
            "clusters": [],
        }

    k = _resolve_k(
        len(usable_vectors),
        requested_clusters=requested_clusters,
        target_cluster_size=cfg["target_cluster_size"],
        max_clusters=cfg["max_clusters"],
    )
    assignments, centroids, iterations = _kmeans_cosine(
        usable_vectors,
        k,
        max_iterations=cfg["max_iterations"],
        random_seed=cfg["random_seed"],
    )

    clusters_summary: list[dict[str, Any]] = []
    for cluster_index in range(k):
        member_indices = [idx for idx, assigned in enumerate(assignments) if assigned == cluster_index]
        member_texts = [str(usable_rows[idx].get("content") or "") for idx in member_indices]
        top_terms = _cluster_terms(member_texts, max_terms=max_terms)
        label = _build_cluster_label(cluster_index, top_terms)

        exemplar_idx = None
        exemplar_score = -2.0
        for idx in member_indices:
            score = _cosine_similarity(usable_vectors[idx], centroids[cluster_index])
            if score > exemplar_score:
                exemplar_score = score
                exemplar_idx = idx
        exemplar_chunk_id = int(usable_rows[exemplar_idx]["chunk_id"]) if exemplar_idx is not None else None

        cur = conn.execute(
            """
            INSERT INTO unsupervised_clusters (
                run_id,
                cluster_index,
                label,
                size,
                top_terms_json,
                exemplar_chunk_id,
                centroid_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                run_id,
                cluster_index,
                label,
                len(member_indices),
                json.dumps(top_terms, ensure_ascii=True),
                exemplar_chunk_id,
                json.dumps(centroids[cluster_index], ensure_ascii=True),
            ),
        )
        cluster_id = int(cur.lastrowid)

        for idx in member_indices:
            chunk_id = int(usable_rows[idx]["chunk_id"])
            score = _cosine_similarity(usable_vectors[idx], centroids[cluster_index])
            conn.execute(
                """
                INSERT INTO unsupervised_cluster_members (
                    cluster_id,
                    run_id,
                    chunk_id,
                    assignment_score
                ) VALUES (?, ?, ?, ?);
                """,
                (cluster_id, run_id, chunk_id, float(score)),
            )

        clusters_summary.append(
            {
                "cluster_id": cluster_id,
                "cluster_index": cluster_index,
                "label": label,
                "size": len(member_indices),
                "top_terms": top_terms,
                "exemplar_chunk_id": exemplar_chunk_id,
            }
        )

    completed_at = _utc_now_iso()
    note = (
        f"Clustering complete. chunks={len(usable_rows)}, clusters={k}, "
        f"vector_source={vector_source}, iterations={iterations}"
    )
    conn.execute(
        """
        UPDATE unsupervised_runs
        SET vector_source = ?, resolved_clusters = ?, min_points = ?, chunk_count = ?, completed_at = ?, notes = ?
        WHERE id = ?;
        """,
        (vector_source, k, minimum, len(usable_rows), completed_at, note, run_id),
    )

    return {
        "ok": True,
        "run_id": run_id,
        "status": "completed",
        "message": note,
        "vector_source": vector_source,
        "chunk_count": len(usable_rows),
        "requested_clusters": requested_clusters,
        "resolved_clusters": k,
        "iterations": iterations,
        "clusters": sorted(clusters_summary, key=lambda item: item["size"], reverse=True),
    }


def list_unsupervised_runs(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            id,
            algorithm,
            vector_source,
            requested_clusters,
            resolved_clusters,
            min_points,
            chunk_count,
            scientific_field,
            vocational_discipline,
            source_collection,
            started_at,
            completed_at,
            notes
        FROM unsupervised_runs
        ORDER BY id DESC
        LIMIT ?;
        """,
        (max(1, min(500, int(limit))),),
    ).fetchall()
    return [dict(row) for row in rows]


def list_unsupervised_clusters(
    conn: sqlite3.Connection,
    *,
    run_id: int | None = None,
    limit: int = 250,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        c.id,
        c.run_id,
        c.cluster_index,
        c.label,
        c.size,
        c.top_terms_json,
        c.exemplar_chunk_id,
        c.centroid_json
    FROM unsupervised_clusters c
    """
    args: list[Any] = []
    if run_id is not None and run_id > 0:
        sql += " WHERE c.run_id = ?"
        args.append(int(run_id))
    sql += " ORDER BY c.run_id DESC, c.size DESC, c.cluster_index ASC LIMIT ?"
    args.append(max(1, min(1000, int(limit))))

    rows = []
    for row in conn.execute(sql, tuple(args)).fetchall():
        item = dict(row)
        try:
            item["top_terms"] = json.loads(item.pop("top_terms_json") or "[]")
        except Exception:
            item["top_terms"] = []
            item.pop("top_terms_json", None)
        item.pop("centroid_json", None)
        rows.append(item)
    return rows


def list_cluster_members(
    conn: sqlite3.Connection,
    cluster_id: int,
    *,
    limit: int = 120,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            m.cluster_id,
            m.chunk_id,
            m.assignment_score,
            c.chunk_index,
            c.content,
            d.source_id,
            d.title,
            d.source_type,
            d.source_path,
            d.source_url,
            d.scientific_field,
            d.vocational_discipline,
            d.source_collection
        FROM unsupervised_cluster_members m
        JOIN chunks c ON c.id = m.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE m.cluster_id = ?
        ORDER BY m.assignment_score DESC, m.chunk_id ASC
        LIMIT ?;
        """,
        (int(cluster_id), max(1, min(1000, int(limit)))),
    ).fetchall()
    return [dict(row) for row in rows]
