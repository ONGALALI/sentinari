"""Sentinel Domains: scientific field registry for the SMI knowledge database.

The five Sentinel domains (Foundations of Reality, Life and Biological Systems,
Human Behavior and Society, Applied Systems and Technology, Health Safety and
Well-Being) each own a set of scientific fields. Every field is a data room:
a taxonomy folder under data/knowledge_taxonomy/scientific_fields/<slug> plus a
row in the sentinel_scientific_fields SQLite table that documents are attached
to when they are uploaded or ingested from GitHub datasets.

All documents ingested through these lanes are tagged with the field's
scientific_field value so the main LLM (Gateway Guardian) retrieves them from
their proper room.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import sqlite3
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from .config import get_project_root
from . import load_progress
from .db import get_connection, try_write_lock
from .ingestion import ingest_files


# ---------------------------------------------------------------------------
# Registry: Sentinel domain -> scientific fields
# ---------------------------------------------------------------------------

SENTINEL_DOMAINS: list[dict[str, Any]] = [
    {
        "slug": "foundations-of-reality",
        "name": "Foundations of Reality (Guardian of Matter & Energy)",
        "description": "Explains the laws of physics, chemistry, mathematics, astronomy, and earth sciences — the skeleton of the universe.",
        "fields": [
            {"name": "Physics", "detail": "quantum, relativity, thermodynamics, particle physics"},
            {"name": "Chemistry", "detail": "atomic, molecular, materials science"},
            {"name": "Mathematics", "slug": "mathematics", "detail": "pure & applied mathematics, geometry, differential equations, statistics"},
            {"name": "Astronomy & Cosmology", "detail": "galaxies, universe structure, astrophysics"},
            {"name": "Earth Sciences", "detail": "geology, meteorology, oceanography"},
        ],
    },
    {
        "slug": "life-and-biological-systems",
        "name": "Life and Biological Systems (Guardian of Living Order)",
        "description": "Decodes life's mechanisms and sustains ecosystems.",
        "fields": [
            {"name": "Biology", "detail": "cellular, evolutionary, ecological"},
            {"name": "Genetics & Molecular Biology", "detail": "genes, DNA, proteomics"},
            {"name": "Neuroscience", "detail": "brain, nervous system, cognition"},
            {"name": "Ecology & Environmental Biology", "detail": "ecosystems, biodiversity, habitats"},
        ],
    },
    {
        "slug": "human-behavior-and-society",
        "name": "Human Behavior and Society (Guardian of Minds & Cultures)",
        "description": "Studies human decision-making, culture, laws, conflict, belief systems, and collective survival.",
        "fields": [
            {"name": "Philosophy", "detail": "ethics, epistemology, metaphysics, logic, philosophy of science"},
            {"name": "Psychology", "detail": "cognitive, industrial, clinical"},
            {"name": "Sociology", "detail": "society, institutions, social dynamics"},
            {"name": "Anthropology", "detail": "cultures, human evolution, ethnography"},
            {"name": "Economics", "detail": "markets, finance, macro and micro economics"},
            {"name": "Political Science", "detail": "governance, policy, international relations"},
            {
                "name": "Laws per Country and International Law",
                "slug": "laws-per-country-and-international-law",
                "detail": "domestic legislation, constitutional & comparative law, treaties, international & humanitarian law",
            },
            {
                "name": "War",
                "slug": "war",
                "detail": "military strategy, conflict studies, defense systems, peace & security, asymmetric & geopolitical warfare",
            },
            {
                "name": "Religion",
                "slug": "religion",
                "detail": "theology, comparative religion, sacred texts, religious history, belief systems, faith & society",
            },
        ],
    },
    {
        "slug": "applied-systems-and-technology",
        "name": "Applied Systems and Technology (Guardian of Tools & Innovation)",
        "description": "Builds solutions and resilience — the bridge between theory and practice.",
        "fields": [
            {"name": "Engineering", "detail": "mechanical, civil, electrical, systems"},
            {"name": "Computer Science & AI", "slug": "computer-and-information-sciences", "detail": "algorithms, machine learning, robotics"},
            {"name": "Information Science", "detail": "data, libraries, information systems"},
            {"name": "Materials Science", "detail": "polymers, composites, nanomaterials"},
        ],
    },
    {
        "slug": "health-safety-and-well-being",
        "name": "Health, Safety, and Well-Being (Guardian of Life's Continuity)",
        "description": "Protects continuity of life: medicine, treatment, prevention, and environment.",
        "fields": [
            {"name": "Medicine", "detail": "clinical practice, anatomy, disease"},
            {"name": "Pharmacology", "detail": "drugs, dosing, interactions"},
            {"name": "Public Health", "detail": "epidemiology, prevention, health systems"},
            {"name": "Environmental Science", "detail": "pollution, climate impact, sustainability"},
        ],
    },
]

# Sentinel main-LLM vector rooms (accumulated across domains). Each room maps
# to one or more scientific fields so uploaded data lands in its proper room.
SENTINEL_ROOMS: list[dict[str, Any]] = [
    {"name": "Physics & Astronomy", "fields": ["Physics", "Astronomy & Cosmology"]},
    {"name": "Chemistry & Materials", "fields": ["Chemistry", "Materials Science"]},
    {"name": "Biology & Genetics", "fields": ["Biology", "Genetics & Molecular Biology"]},
    {"name": "Medicine & Health", "fields": ["Medicine", "Pharmacology", "Public Health"]},
    {"name": "Earth & Climate Sciences", "fields": ["Earth Sciences", "Environmental Science"]},
    {"name": "Computer Science, AI Engineering & Robotics", "fields": ["Computer Science & AI", "Information Science", "Engineering"]},
    {"name": "Mathematics & Statistics", "fields": ["Mathematics"]},
    {"name": "Neuroscience & Psychology", "fields": ["Neuroscience", "Psychology", "Philosophy"]},
    {"name": "Social Sciences", "fields": ["Sociology", "Anthropology"]},
    {"name": "Economics", "fields": ["Economics"]},
    {"name": "Agricultural & Food Sciences", "fields": []},
    {"name": "Space Exploration & Aerospace", "fields": []},
    {"name": "Political Science", "fields": ["Political Science"]},
    {"name": "Laws, War & Religion", "fields": ["Laws per Country and International Law", "War", "Religion"]},
]


# Per-field capacity used for the progress bars: a bar fills toward this cap
# and turns red when the field reaches it.
SENTINEL_FIELD_CAP_MB = 1000


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text or "unnamed"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def purge_field_documents(field: str, doc_ids: list[int], *, keep_docs: list[int] | None = None) -> dict[str, int]:
    """Remove documents (and every chunk/FTS row) from a field's library.

    Owner directive: a failed load must leave **nothing** behind — partial
    chunks are deleted and the whole field's library is left clean.
    """
    keep = {int(d) for d in (keep_docs or [])}
    targets = [int(d) for d in doc_ids if int(d) > 0 and int(d) not in keep]
    removed_documents = 0
    removed_chunks = 0
    if targets:
        from .db import library_connection

        placeholders = ",".join("?" for _ in targets)
        with library_connection("gemma") as conn:
            removed_chunks = int(
                conn.execute(
                    f"SELECT COUNT(1) AS n FROM chunks WHERE document_id IN ({placeholders});", targets
                ).fetchone()["n"]
            )
            conn.execute(f"DELETE FROM chunks WHERE document_id IN ({placeholders});", targets)
            conn.execute(f"DELETE FROM chunk_fts WHERE document_id IN ({placeholders});", targets)
            conn.execute(f"DELETE FROM documents WHERE id IN ({placeholders});", targets)
            conn.commit()
        removed_documents = len(targets)
        _refresh_field_counts_safe(field)
    return {"removed_documents": removed_documents, "removed_chunks": removed_chunks}


def _refresh_field_counts_safe(field: str) -> None:
    """Best-effort count refresh after a purge (never masks a purge failure)."""
    try:
        resolved = _resolve_field(field)
    except Exception:
        return
    try:
        with library_connection("gemma") as conn:
            _refresh_field_counts(conn)
            conn.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Database schema + ensure logic
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sentinel_domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sentinel_scientific_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_slug TEXT NOT NULL,
    field_name TEXT NOT NULL,
    field_slug TEXT NOT NULL UNIQUE,
    detail TEXT NOT NULL DEFAULT '',
    taxonomy_path TEXT NOT NULL DEFAULT '',
    documents INTEGER NOT NULL DEFAULT 0,
    chunks INTEGER NOT NULL DEFAULT 0,
    bytes_total INTEGER NOT NULL DEFAULT 0,
    last_ingest_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sentinel_fields_domain ON sentinel_scientific_fields(domain_slug);
"""


def ensure_sentinel_database(conn: Any = None) -> dict[str, Any]:
    """Create the sentinel tables and every domain/field row that is missing.

    Safe to call repeatedly (idempotent). Returns a report of what exists and
    what was created. Pass an open sqlite connection to reuse a transaction.
    """
    owned = conn is None
    if owned:
        from .db import library_connection

        conn_cm = library_connection("gemma")
        conn = conn_cm
    try:
        conn.executescript(_SCHEMA)

        report: dict[str, Any] = {"domains_created": 0, "fields_created": 0, "domains": []}
        taxonomy_root = get_project_root() / "data" / "knowledge_taxonomy" / "scientific_fields"

        for domain in SENTINEL_DOMAINS:
            domain_slug = str(domain.get("slug") or "")
            existing_domain = conn.execute(
                "SELECT id FROM sentinel_domains WHERE slug = ?;", (domain_slug,)
            ).fetchone()
            if existing_domain is None:
                conn.execute(
                    "INSERT OR IGNORE INTO sentinel_domains (slug, name, description) VALUES (?, ?, ?);",
                    (domain_slug, str(domain.get("name") or ""), str(domain.get("description") or "")),
                )
                report["domains_created"] += 1

            domain_report: dict[str, Any] = {"slug": domain_slug, "fields_created": [], "fields_total": 0}
            for field in domain.get("fields", []):
                field_name = str(field.get("name") or "").strip()
                if not field_name:
                    continue
                field_slug = str(field.get("slug") or "").strip() or slugify(field_name)
                target_dir = taxonomy_root / slugify(field_slug)
                target_dir.mkdir(parents=True, exist_ok=True)
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO sentinel_scientific_fields
                        (domain_slug, field_name, field_slug, detail, taxonomy_path)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (
                        domain_slug,
                        field_name,
                        field_slug,
                        str(field.get("detail") or ""),
                        str(target_dir),
                    ),
                )
                if cursor.rowcount and cursor.rowcount > 0:
                    report["fields_created"] += 1
                    domain_report["fields_created"].append(field_name)
                domain_report["fields_total"] += 1
            report["domains"].append(domain_report)

        conn.commit()
        report["ok"] = True
        return report
    finally:
        if owned:
            try:
                conn_cm.close()
            except Exception:
                pass


def _refresh_field_counts(conn: Any) -> None:
    conn.execute(
        """
        UPDATE sentinel_scientific_fields
        SET
            documents = COALESCE((SELECT COUNT(1) FROM documents d WHERE d.scientific_field = sentinel_scientific_fields.field_slug), 0),
            chunks = COALESCE((SELECT COUNT(1) FROM chunks c JOIN documents d ON d.id = c.document_id WHERE d.scientific_field = sentinel_scientific_fields.field_slug), 0),
            bytes_total = COALESCE((SELECT SUM(d.raw_char_count) FROM documents d WHERE d.scientific_field = sentinel_scientific_fields.field_slug), 0)
        ;
        """
    )
    conn.execute(
        """
        UPDATE sentinel_scientific_fields
        SET last_ingest_at = COALESCE(
            (SELECT MAX(e.created_at) FROM ingest_events e WHERE e.scientific_field = sentinel_scientific_fields.field_slug AND e.status = 'ok'),
            last_ingest_at
        );
        """
    )


def _sentinel_schema_present() -> bool:
    """True when the sentinel tables and all registered fields exist in the library database.

    Cheap read-only check used to skip the DDL ensure pass on steady-state
    status calls (§77 anti-stall fix).
    """
    try:
        from .db import library_read_connection

        conn = library_read_connection(busy_timeout_ms=500)
    except Exception:
        return False
    try:
        expected_fields = sum(len(d.get("fields", [])) for d in SENTINEL_DOMAINS)
        row = conn.execute("SELECT COUNT(1) FROM sentinel_scientific_fields;").fetchone()
        return int(row[0] or 0) >= expected_fields
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_sentinel_status(*, refresh_counts: bool = False) -> dict[str, Any]:
    """Status snapshot for the playground UI: domains, fields, progress, MB.

    Lock-tolerant: when the shared SQLite database is busy with a long write
    (e.g. an ingestion worker mid-transaction), degrade gracefully instead of
    failing the dashboard with `database is locked`. The schema ensure and the
    field-count refresh are best-effort; reads always proceed.
    """
    write_available = try_write_lock(timeout_ms=1500) is not None
    from .db import try_library_write_lock

    # The sentinel tables live in the LIBRARY database: an ensure pass is a
    # write there, so a mid-load learning engine holding the library lock
    # would stall this endpoint for the full busy timeout (20s) even with a
    # free main database. Schema exists in steady state; skip when busy.
    library_write_free = try_library_write_lock(timeout_ms=750)
    if write_available and library_write_free:
        try:
            # §77: steady-state fast path — the sentinel schema is created once
            # by /sentinel/ensure or first use. Re-running the DDL script here
            # on every status call turned any lock grabbed between the probe
            # and the write into a 20s stall. Only ensure when actually absent.
            if not _sentinel_schema_present():
                ensure_sentinel_database()
        except Exception as ensure_ex:
            # Schema already exists in steady state; a locked database just means
            # the ensure pass must wait for a quieter moment.
            try:
                (get_project_root() / "Logs").mkdir(parents=True, exist_ok=True)
                with open(get_project_root() / "Logs" / "sentinel-ensure.log", "a", encoding="utf-8") as _log_handle:
                    _log_handle.write(f"[{datetime.utcnow().isoformat()}] get_sentinel_status ensure deferred: {ensure_ex!r}\n")
            except Exception:
                pass
    conn = None
    try:
        # Read-only by default: a bulk ingestion writer holding the write lock
        # (WAL allows concurrent readers) must not stall this endpoint long
        # enough for the browser to abort the fetch. Only take the read/write
        # connection when the LIBRARY lock is also free — a count refresh is a
        # write against the library database, so checking only the main
        # database still allowed a mid-load learning engine to stall us.
        from .db import library_connection, library_read_connection

        try:
            if refresh_counts and write_available and library_write_free:
                conn = library_connection("gemma", busy_timeout_ms=1500)
            else:
                conn = library_read_connection()
        except FileNotFoundError:
            conn = library_connection("gemma")  # first run: create the library
    except Exception:
        raise
    try:
        if conn is not None and refresh_counts and write_available and library_write_free:
            try:
                _refresh_field_counts(conn)
                conn.commit()
            except Exception as refresh_ex:
                try:
                    conn.rollback()
                except Exception:
                    pass
                try:
                    (get_project_root() / "Logs").mkdir(parents=True, exist_ok=True)
                    with open(get_project_root() / "Logs" / "sentinel-ensure.log", "a", encoding="utf-8") as _log_handle:
                        _log_handle.write(f"[{datetime.utcnow().isoformat()}] get_sentinel_status count-refresh deferred: {refresh_ex!r}\n")
                except Exception:
                    pass
        domain_rows = {
            row["slug"]: dict(row)
            for row in conn.execute("SELECT slug, name, description FROM sentinel_domains ORDER BY id;").fetchall()
        }
        field_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT domain_slug, field_name, field_slug, detail, taxonomy_path, documents, chunks, bytes_total, last_ingest_at FROM sentinel_scientific_fields ORDER BY id;"
            ).fetchall()
        ]
    finally:
        try:
            conn.close()
        except Exception:
            pass

    domains_out: list[dict[str, Any]] = []
    total_documents = 0
    total_chunks = 0
    total_bytes = 0
    for domain in SENTINEL_DOMAINS:
        slug = str(domain.get("slug") or "")
        fields_out: list[dict[str, Any]] = []
        for field in domain.get("fields", []):
            field_name = str(field.get("name") or "")
            field_slug = str(field.get("slug") or "").strip() or slugify(field_name)
            row = next((r for r in field_rows if r.get("field_slug") == field_slug), None)
            documents = int((row or {}).get("documents") or 0)
            chunks = int((row or {}).get("chunks") or 0)
            bytes_total = int((row or {}).get("bytes_total") or 0)
            total_documents += documents
            total_chunks += chunks
            total_bytes += bytes_total
            fields_out.append(
                {
                    "field_name": field_name,
                    "field_slug": field_slug,
                    "detail": str(field.get("detail") or ""),
                    "documents": documents,
                    "chunks": chunks,
                    "bytes_total": bytes_total,
                    "mb_total": round(bytes_total / (1024.0 * 1024.0), 2),
                    "cap_pct": round(min(bytes_total / (SENTINEL_FIELD_CAP_MB * 1024.0 * 1024.0) * 100.0, 100.0), 2),
                    "last_ingest_at": str((row or {}).get("last_ingest_at") or ""),
                    "taxonomy_path": str((row or {}).get("taxonomy_path") or ""),
                }
            )
        domains_out.append(
            {
                "slug": slug,
                "name": str(domain.get("name") or ""),
                "description": str(domain.get("description") or ""),
                "db_name": str((domain_rows.get(slug) or {}).get("name") or domain.get("name") or ""),
                "fields": fields_out,
            }
        )

    return {
        "ok": True,
        "main_model": "Sentinari 12B",
        "field_cap_mb": SENTINEL_FIELD_CAP_MB,
        "rooms": [dict(room) for room in SENTINEL_ROOMS],
        "domains": domains_out,
        "totals": {
            "domains": len(domains_out),
            "fields": sum(len(d.get("fields", [])) for d in domains_out),
            "documents": total_documents,
            "chunks": total_chunks,
            "bytes_total": total_bytes,
            "mb_total": round(total_bytes / (1024.0 * 1024.0), 2),
            "field_cap_mb": SENTINEL_FIELD_CAP_MB,
        },
        "timestamp_utc": _utc_now(),
    }


_FIELD_ALIASES: dict[str, str] = {
    "quantum-physics": "physics",
    "quantum-doctrine-rd": "physics",
    "theoretical-physics": "physics",
    "math": "mathematics",
    "maths": "mathematics",
    "pure-mathematics": "mathematics",
    "applied-mathematics": "mathematics",
    "statistics": "mathematics",
    "algebra": "mathematics",
    "geometry": "mathematics",
    "calculus": "mathematics",
    "astrophysics": "astronomy-cosmology",
    "astronomy": "astronomy-cosmology",
    "cosmology": "astronomy-cosmology",
    "astronomy-and-cosmology": "astronomy-cosmology",
    "earth-science": "earth-sciences",
    "geology": "earth-sciences",
    "genetics": "genetics-molecular-biology",
    "molecular-biology": "genetics-molecular-biology",
    "genetics-and-molecular-biology": "genetics-molecular-biology",
    "stem-cell-biology": "genetics-molecular-biology",
    "computational-biology": "genetics-molecular-biology",
    "biochemistry": "genetics-molecular-biology",
    "ecology": "ecology-environmental-biology",
    "environmental-biology": "ecology-environmental-biology",
    "ecology-and-environmental-biology": "ecology-environmental-biology",
    "developmental-biology": "biology",
    "cell-biology": "biology",
    "virology": "biology",
    "microbiology": "biology",
    "neurobiology": "neuroscience",
    "neuropsychiatry": "neuroscience",
    "neurology": "neuroscience",
    "cognitive-neuroscience": "neuroscience",
    "oncology": "medicine",
    "immunology": "medicine",
    "pathophysiology": "medicine",
    "cardiology": "medicine",
    "psychiatry": "medicine",
    "clinical-pharmacology": "pharmacology",
    "toxicology": "pharmacology",
    "health-policy": "public-health",
    "epidemiology": "public-health",
    "bioengineering": "engineering",
    "biomedical-engineering": "engineering",
    "media-engineering": "engineering",
    "epistemology": "philosophy",
    "ethics": "philosophy",
    "metaphysics": "philosophy",
    "governance": "political-science",
    "institutional-design": "political-science",
    "public-policy": "political-science",
    "law": "laws-per-country-and-international-law",
    "laws": "laws-per-country-and-international-law",
    "laws-per-country": "laws-per-country-and-international-law",
    "international-law": "laws-per-country-and-international-law",
    "comparative-law": "laws-per-country-and-international-law",
    "constitutional-law": "laws-per-country-and-international-law",
    "legal": "laws-per-country-and-international-law",
    "legal-studies": "laws-per-country-and-international-law",
    "jurisprudence": "laws-per-country-and-international-law",
    "warfare": "war",
    "military": "war",
    "military-science": "war",
    "military-strategy": "war",
    "conflict-studies": "war",
    "defense": "war",
    "defence": "war",
    "relegion": "religion",
    "theology": "religion",
    "comparative-religion": "religion",
    "religious-studies": "religion",
    "faith": "religion",
    "organizational-theory": "sociology",
    "social-work": "sociology",
    "computer-science": "computer-and-information-sciences",
    "computer-science-ai": "computer-and-information-sciences",
    "computer-science-and-ai": "computer-and-information-sciences",
    "artificial-intelligence": "computer-and-information-sciences",
    "data-science": "information-science",
    "material-science": "materials-science",
    "finance": "economics",
    "strategic-management": "economics",
    "management": "economics",
}

_KEYWORD_FIELD_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("buckminsterfullerene", "fullerene", "c60", "c70", "molecule", "chemical", "catalys", "organic chemistry", "inorganic", "polymer", "stoichiometr"), "chemistry"),
    (("newton", "gravity", "gravitation", "quantum", "relativity", "thermodynamic", "lagrangian", "hamiltonian", "boson", "fermion", "electrodynamic", "photon", "schrodinger"), "physics"),
    (("pure mathematics", "applied mathematics", "differential equation", "cluster algebra", "topology", "number theory", "linear algebra", "calculus", "riemann", "hilbert space", "group theory", "bayesian", "theorem", "combinatorics", "stochastic"), "mathematics"),
    (("galaxy", "cosmolog", "astrophys", "supernova", "exoplanet", "black hole", "stellar"), "astronomy-cosmology"),
    (("geolog", "seismic", "tectonic", "meteorolog", "oceanograph", "stratigraph"), "earth-sciences"),
    (("crispr", "genome", "dna", "rna", "proteom", "transcription", "allele", "ribosom", "stem cell"), "genetics-molecular-biology"),
    (("neuron", "synap", "cortex", "brain", "nervous system", "hippocamp", "neuro", "assembloid", "thalamic", "striatal"), "neuroscience"),
    (("biodivers", "ecosystem", "habitat", "food web", "trophic"), "ecology-environmental-biology"),
    (("cell", "organism", "evolution", "mitochondr", "photosynthes", "enzyme", "virolog", "autophag", "lysosom"), "biology"),
    (("pharmacokinet", "drug interaction", "dosage", "receptor agonist", "antagonist", "pharmacology", "polypharmacy"), "pharmacology"),
    (("epidemiolog", "pandemic", "vaccination", "mortality rate", "public health", "surveillance", "health policy"), "public-health"),
    (("clinical", "patient", "diagnosis", "syndrome", "oncolog", "cardiol", "surgery", "pathology", "jak inhibitor", "cancer", "tumour", "tumor", "adenoma", "osteosarcoma", "stroke", "immunotherap"), "medicine"),
    (("pollution", "emissions", "climate change", "sustainability", "greenhouse"), "environmental-science"),
    (("epistemolog", "metaphysic", "ethic", "ontology", "qualia", "phenomenolog", "free will"), "philosophy"),
    (("cogniti", "behavior", "psycholog", "psychiatric", "mental health", "perception"), "psychology"),
    (("sociolog", "social norm", "inequality", "demographic", "urbanization", "social work"), "sociology"),
    (("anthropolog", "ethnograph", "archaeolog", "kinship"), "anthropology"),
    (("macroeconom", "microeconom", "inflation", "gdp", "monetary", "fiscal", "insurance", "financial management", "market"), "economics"),
    (("governance", "geopolit", "democracy", "parliament", "election", "institutional design"), "political-science"),
    (("international law", "constitutional law", "comparative law", "treaty", "legislation", "statute", "jurisprudence", "criminal law", "civil law", "humanitarian law", "geneva convention", "sovereignty", "judicial", "legal framework", "laws per country"), "laws-per-country-and-international-law"),
    (("warfare", "military strategy", "armed conflict", "battlefield", "insurgency", "counterinsurgency", "deterrence", "geopolitical conflict", "clausewitz", "asymmetric war", "defense system", "artillery", "naval", "airpower"), "war"),
    (("religion", "relegion", "theolog", "sacred text", "scripture", "monotheis", "polytheis", "liturg", "eschatolog", "hermeneutic", "faith", "ecclesi", "buddhis", "christian", "islam", "judaism", "hindu"), "religion"),
    (("nanomaterial", "composite", "alloy", "crystal lattice", "perovskite", "semiconductor material"), "materials-science"),
    (("circuit", "mechanical", "aerospace", "civil engineering", "robotics", "control system", "finite element", "bioengineering"), "engineering"),
    (("algorithm", "compiler", "neural network", "machine learning", "kubernetes", "linux", "python", "database", "encryption", "software"), "computer-and-information-sciences"),
)


def _domain_for_field_slug(field_slug: str) -> str:
    wanted = slugify(field_slug)
    for domain in SENTINEL_DOMAINS:
        d_slug = str(domain.get("slug") or "")
        for item in domain.get("fields", []):
            name = str(item.get("name") or "")
            item_slug = str(item.get("slug") or "").strip() or slugify(name)
            if item_slug == wanted or slugify(name) == wanted:
                return d_slug
    return ""


def infer_field_from_text(text: str, default_field: str = "") -> str:
    """Infer the canonical Sentinel field_slug from query/title/description text."""
    hay = str(text or "").lower()
    if not hay.strip():
        return default_field
    if any(k in hay for k in ("pure mathematics", "applied mathematics", "cluster algebra", "differential equation", "bayesian statistics", "mathematical practice")):
        return "mathematics"
    best_field = ""
    best_hits = 0
    for keywords, f_slug in _KEYWORD_FIELD_HINTS:
        hits = sum(1 for kw in keywords if kw in hay)
        if hits > best_hits:
            best_hits = hits
            best_field = f_slug
    return best_field or default_field


def sanitize_field_and_domain(
    field: str | None = None,
    fallback_text: str = "",
    *,
    domain: str | None = None,
    title: str | None = None,
    text: str | None = None,
) -> tuple[str, str]:
    """Sanitize any field/domain input into a canonical (field_slug, domain_slug) pair.

    Handles exact slugs, human display names ('Earth Sciences'), legacy aliases
    ('Quantum Physics'), detail strings, or empty fields (inferred from fallback_text).
    """
    combined_fallback = " ".join(
        p for p in (fallback_text, str(title or "").strip(), str(text or "").strip()) if p
    ).strip()
    raw = str(field or "").strip()
    raw_dom = str(domain or "").strip()
    if raw:
        try:
            f_slug = resolve_field_loose(raw)
            return f_slug, _domain_for_field_slug(f_slug)
        except Exception:
            pass
        # Check if raw is actually a Sentinel domain slug/name
        wanted = slugify(raw)
        for dom in SENTINEL_DOMAINS:
            d_slug = str(dom.get("slug") or "")
            if wanted == d_slug or wanted == slugify(str(dom.get("name") or "")):
                inferred = infer_field_from_text(combined_fallback)
                if inferred and _domain_for_field_slug(inferred) == d_slug:
                    return inferred, d_slug
                first_item = (dom.get("fields") or [{}])[0]
                first_slug = str(first_item.get("slug") or "").strip() or slugify(str(first_item.get("name") or ""))
                return first_slug, d_slug
    if raw_dom and not raw:
        wanted_dom = slugify(raw_dom)
        for dom in SENTINEL_DOMAINS:
            d_slug = str(dom.get("slug") or "")
            if wanted_dom == d_slug or wanted_dom == slugify(str(dom.get("name") or "")):
                inferred = infer_field_from_text(combined_fallback)
                if inferred and _domain_for_field_slug(inferred) == d_slug:
                    return inferred, d_slug
                first_item = (dom.get("fields") or [{}])[0]
                first_slug = str(first_item.get("slug") or "").strip() or slugify(str(first_item.get("name") or ""))
                return first_slug, d_slug
    inferred = infer_field_from_text(f"{raw} {combined_fallback}")
    if inferred:
        return inferred, _domain_for_field_slug(inferred)
    return "", ""



def sanitize_pattern_fields(
    fields_raw: Any,
    *,
    fallback_field: str = "",
    fallback_text: str = "",
) -> list[str]:
    """Normalize any list or JSON array of field names into deduplicated canonical Sentinel field_slugs."""
    items: list[str] = []
    if isinstance(fields_raw, str):
        raw_str = fields_raw.strip()
        if raw_str.startswith("["):
            try:
                parsed = json.loads(raw_str)
                if isinstance(parsed, list):
                    items = [str(x or "").strip() for x in parsed if str(x or "").strip()]
            except Exception:
                items = [raw_str]
        elif "+" in raw_str:
            items = [p.strip() for p in raw_str.split("+") if p.strip()]
        elif raw_str:
            items = [raw_str]
    elif isinstance(fields_raw, (list, tuple, set)):
        items = [str(x or "").strip() for x in fields_raw if str(x or "").strip()]

    canonical: list[str] = []
    # Also remember if a raw item explicitly distinguishes two sub-specialties that map to
    # e.g. neuroscience + medicine (like 'neuropsychiatry' -> neuroscience + medicine).
    for item in items:
        low = slugify(item)
        if low == "neuropsychiatry":
            for slug in ("neuroscience", "medicine"):
                if slug not in canonical:
                    canonical.append(slug)
            continue
        f_slug, _ = sanitize_field_and_domain(item)
        if f_slug and f_slug not in canonical:
            canonical.append(f_slug)

    if not canonical and (fallback_field or fallback_text):
        fb_slug, _ = sanitize_field_and_domain(fallback_field, fallback_text=fallback_text)
        if fb_slug:
            canonical.append(fb_slug)
    return canonical


def resolve_domain_or_field_filter(value: str | None) -> tuple[str | None, list[str]]:
    """Resolve a filter string (domain slug/name, room name, or field slug/name)
    into (domain_slug_or_None, list_of_canonical_field_slugs)."""
    text = str(value or "").strip()
    if not text:
        return None, []
    wanted = slugify(text)
    # 1. Check if it matches one of the 5 Sentinel Domains
    for domain in SENTINEL_DOMAINS:
        d_slug = str(domain.get("slug") or "")
        d_name_slug = slugify(str(domain.get("name") or ""))
        if wanted == d_slug or wanted == d_name_slug or (len(wanted) >= 8 and d_slug.startswith(wanted)):
            f_slugs = [
                str(item.get("slug") or "").strip() or slugify(str(item.get("name") or ""))
                for item in (domain.get("fields") or [])
            ]
            return d_slug, [s for s in f_slugs if s]
    # 2. Check if it matches a Sentinel Room
    for room in SENTINEL_ROOMS:
        if wanted == slugify(str(room.get("name") or "")):
            f_slugs = []
            for fname in room.get("fields") or []:
                try:
                    f_slugs.append(resolve_field_loose(fname))
                except Exception:
                    pass
            if f_slugs:
                return None, f_slugs
    # 3. Resolve as a single scientific field
    try:
        f_slug = resolve_field_loose(text)
        return None, [f_slug]
    except Exception:
        return None, [wanted]


def _resolve_field(field: str) -> dict[str, Any]:
    try:
        ensure_sentinel_database()
    except sqlite3.OperationalError as ensure_ex:
        if "locked" not in str(ensure_ex).lower():
            raise
        try:
            (get_project_root() / "Logs").mkdir(parents=True, exist_ok=True)
            with open(get_project_root() / "Logs" / "sentinel-ensure.log", "a", encoding="utf-8") as _log_handle:
                _log_handle.write(
                    f"[{datetime.utcnow().isoformat()}] _resolve_field ensure deferred (library busy): {ensure_ex!r}\n"
                )
        except Exception:
            pass
    wanted = slugify(str(field or ""))
    wanted = _FIELD_ALIASES.get(wanted, wanted)
    for domain in SENTINEL_DOMAINS:
        for item in domain.get("fields", []):
            name = str(item.get("name") or "")
            item_slug = str(item.get("slug") or "").strip() or slugify(name)
            if item_slug == wanted or slugify(name) == wanted:
                target_dir = get_project_root() / "data" / "knowledge_taxonomy" / "scientific_fields" / item_slug
                return {
                    "domain_slug": str(domain.get("slug") or ""),
                    "field_name": name,
                    "field_slug": item_slug,
                    "detail": str(item.get("detail") or ""),
                    "target_dir": target_dir,
                }
    raise ValueError(f"Unknown Sentinel scientific field: {field!r}")


def resolve_field_loose(field: str) -> str:
    """Resolve a field to its slug, tolerating human names, aliases, and detail strings."""
    text = str(field or "").strip()
    if not text:
        raise ValueError("No scientific field provided.")
    wanted = slugify(text)
    wanted = _FIELD_ALIASES.get(wanted, wanted)
    for domain in SENTINEL_DOMAINS:
        for item in domain.get("fields", []):
            name = str(item.get("name") or "")
            item_slug = str(item.get("slug") or "").strip() or slugify(name)
            if item_slug == wanted or slugify(name) == wanted:
                return item_slug
            detail = str(item.get("detail") or "").strip()
            if detail and (detail.lower() == text.lower() or slugify(detail) == wanted):
                return item_slug
    inferred = infer_field_from_text(text)
    if inferred:
        return inferred
    raise ValueError(f"Unknown Sentinel scientific field: {field!r}")


def _field_metadata(resolved: dict[str, Any]) -> dict[str, Any]:
    return {
        "scientific_field": resolved["field_slug"],
        "domain": resolved["domain_slug"],
        "publisher": "SMi Sentinel Domains",
        "license": "sentinel-knowledge-base",
        "extra_metadata": {
            "sentinel_domain": resolved["domain_slug"],
            "sentinel_field": resolved["field_name"],
        },
    }


def _note_last_ingest(field_slug: str) -> None:
    from .db import library_connection

    for _attempt in range(3):
        try:
            with library_connection("gemma") as conn:
                conn.execute(
                    """
                    UPDATE sentinel_scientific_fields
                    SET
                        documents = COALESCE((SELECT COUNT(1) FROM documents d WHERE d.scientific_field = ?), 0),
                        chunks = COALESCE((SELECT COUNT(1) FROM chunks c JOIN documents d ON d.id = c.document_id WHERE d.scientific_field = ?), 0),
                        bytes_total = COALESCE((SELECT SUM(d.raw_char_count) FROM documents d WHERE d.scientific_field = ?), 0),
                        last_ingest_at = ?
                    WHERE field_slug = ?;
                    """,
                    (field_slug, field_slug, field_slug, _utc_now(), field_slug),
                )
                conn.commit()
            return
        except Exception as ex:
            if "locked" not in str(ex).lower():
                break
            time.sleep(0.5)
    print(f"[sentinel] note: could not stamp last_ingest_at for {field_slug} (database busy) — data is safely stored.")


# ---------------------------------------------------------------------------
# PDF / document upload per field
# ---------------------------------------------------------------------------

def ingest_sentinel_field_files(
    field: str,
    stored_paths: list[str],
    *,
    module: str = "uploaded-document",
    topic: str = "sentinel-upload",
) -> dict[str, Any]:
    """Ingest uploaded PDFs/documents into the requested scientific field."""
    resolved = _resolve_field(field)
    metadata = _field_metadata(resolved)
    metadata.update({"module": module, "topic": topic, "priority": 150})
    result = ingest_files(stored_paths, metadata=metadata, allow_embeddings=True)
    _note_last_ingest(resolved["field_slug"])
    items = result.get("items") or []
    ingested_count = int(result.get("ingested") or 0)
    first_error = next((str(item.get("error") or "") for item in items if item.get("error")), "")
    total_chunks = sum(int(item.get("chunk_count") or item.get("chunks_created") or 0) for item in items if isinstance(item, dict))
    out: dict[str, Any] = {
        "ok": ingested_count > 0,
        "field": resolved["field_name"],
        "field_slug": resolved["field_slug"],
        "domain": resolved["domain_slug"],
        "uploaded": len(stored_paths),
        "ingested": ingested_count,
        "chunks_created": total_chunks,
        "failed": int(result.get("failed") or 0),
        "items": items,
        "status": get_sentinel_status(refresh_counts=False),
    }
    if ingested_count <= 0 and first_error:
        out["error"] = first_error
        out["detail"] = first_error
    return out


# ---------------------------------------------------------------------------
# GitHub dataset ingestion per field
# ---------------------------------------------------------------------------

_GITHUB_REPO_PATTERN = re.compile(r"github\.com[/:]([^/]+)/([^/#?]+?)(?:\.git)?(?:[/#?]|$)")
_GITHUB_API_BASE = "https://api.github.com"
_REPO_FILE_SUFFIXES = {
    ".md", ".txt", ".csv", ".json", ".jsonl", ".yaml", ".yml", ".html", ".htm",
    ".pdf", ".py", ".js", ".ts", ".tsx", ".cs", ".sql", ".r", ".ipynb", ".tex",
}
_REPO_IGNORED_PARTS = {".git", ".github", ".next", ".venv", "__pycache__", "bin", "build", "dist", "node_modules", "obj"}


def _github_owner_repo(url: str) -> tuple[str, str]:
    match = _GITHUB_REPO_PATTERN.search(str(url or ""))
    if not match:
        raise ValueError(f"Could not parse a GitHub owner/repo from: {url!r}")
    return match.group(1), match.group(2)


def _bytes_to_mb(num_bytes: float) -> float:
    return round(float(num_bytes) / (1024.0 * 1024.0), 2)


def _github_headers() -> dict[str, str]:
    headers = {"User-Agent": "Sentinari-Sentinel-Domains/1.0", "Accept": "application/vnd.github+json"}
    token = str(os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _select_repo_files(tree: list[dict[str, Any]], *, max_files: int, max_total_mb: float) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    total_bytes = 0
    max_total_bytes = max_total_mb * 1024.0 * 1024.0
    for node in tree:
        if node.get("type") != "blob":
            continue
        path = str(node.get("path") or "")
        if not path or any(part in _REPO_IGNORED_PARTS for part in path.split("/")):
            continue
        if Path(path).suffix.lower() not in _REPO_FILE_SUFFIXES:
            continue
        size = int(node.get("size") or 0)
        if size <= 0 or size > 80 * 1024 * 1024:
            continue
        total_bytes += size
        files.append({"path": path, "size": size, "download_url": str(node.get("url") or "")})
        if len(files) >= max_files or total_bytes >= max_total_bytes:
            break
    return files


def _tree_via_zipball(owner: str, repo: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    """Fetch the repo archive from codeload and derive the file tree from it.

    Used as fallback when the REST tree endpoint is rate limited. File sizes
    are only known after download, so they are reported from the archive.
    """
    resp = requests.get(
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/main",
        headers=headers,
        timeout=120,
    )
    if resp.status_code != 200:
        resp = requests.get(
            f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/master",
            headers=headers,
            timeout=120,
        )
    resp.raise_for_status()

    files: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            parts = member.filename.split("/")
            rel_parts = parts[1:] if len(parts) > 1 else parts
            rel_path = "/".join(rel_parts)
            if not rel_path or any(part in _REPO_IGNORED_PARTS for part in rel_parts):
                continue
            if Path(rel_path).suffix.lower() not in _REPO_FILE_SUFFIXES:
                continue
            size = int(member.file_size or 0)
            if size <= 0 or size > 80 * 1024 * 1024:
                continue
            files.append({"path": rel_path, "size": size, "download_url": "", "zip_member": member.filename})
    return files


def list_github_dataset_files(
    repo_url: str,
    *,
    max_files: int = 200,
    max_total_mb: float = 300.0,
) -> dict[str, Any]:
    """List files a GitHub repo would contribute to a Sentinel field (dry run)."""
    owner, repo = _github_owner_repo(repo_url)
    headers = _github_headers()
    tree: list[dict[str, Any]] = []
    via_zipball = False
    try:
        tree_resp = requests.get(
            f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/HEAD",
            params={"recursive": "1"},
            headers=headers,
            timeout=60,
        )
        if tree_resp.status_code == 404:
            tree_resp = requests.get(
                f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/main",
                params={"recursive": "1"},
                headers=headers,
                timeout=60,
            )
        tree_resp.raise_for_status()
        tree = tree_resp.json().get("tree") or []
    except Exception:
        # REST API rate limited or blocked: fall back to the codeload archive.
        tree = _tree_via_zipball(owner, repo, headers)
        via_zipball = True

    files = _select_repo_files(tree, max_files=max_files, max_total_mb=max_total_mb)
    return {
        "ok": True,
        "repo": f"{owner}/{repo}",
        "files": files,
        "file_count": len(files),
        "total_bytes": sum(int(f.get("size") or 0) for f in files),
        "total_mb": _bytes_to_mb(sum(int(f.get("size") or 0) for f in files)),
        "via_zipball": via_zipball,
    }


def ingest_github_dataset_to_field(
    field: str,
    repo_urls: list[str],
    *,
    max_files_per_repo: int = 200,
    max_total_mb: float = 300.0,
) -> dict[str, Any]:
    # Hard policy clamps: max 1000 files per repo, max 300 MB per repo pull.
    max_files_per_repo = max(1, min(1000, int(max_files_per_repo or 200)))
    max_total_mb = max(1.0, min(300.0, float(max_total_mb or 300.0)))
    """Download a GitHub repository's data files and ingest them into a field."""
    resolved = _resolve_field(field)
    target_root = resolved["target_dir"]
    target_root.mkdir(parents=True, exist_ok=True)

    ingested = 0
    failed = 0
    total_bytes = 0
    items: list[dict[str, Any]] = []
    remaining_paths: list[str] = []

    headers = {"User-Agent": "Sentinari-Sentinel-Domains/1.0", "Accept": "application/vnd.github+json"}

    for repo_url in [str(u or "").strip() for u in repo_urls if str(u or "").strip()]:
        started = time.perf_counter()
        try:
            listing = list_github_dataset_files(
                repo_url, max_files=max_files_per_repo, max_total_mb=max_total_mb
            )
            owner_repo = str(listing.get("repo") or "repo")
            repo_dir = target_root / "github" / slugify(owner_repo)
            repo_dir.mkdir(parents=True, exist_ok=True)

            downloaded: list[str] = []
            repo_bytes = 0
            zip_members = {str(f.get("zip_member") or ""): f for f in listing.get("files", []) if f.get("zip_member")}
            zip_bytes: bytes | None = None
            if zip_members:
                owner_z, repo_z = owner_repo.split("/", 1)
                zresp = requests.get(f"https://codeload.github.com/{owner_z}/{repo_z}/zip/refs/heads/main", headers=headers, timeout=180)
                if zresp.status_code != 200:
                    zresp = requests.get(f"https://codeload.github.com/{owner_z}/{repo_z}/zip/refs/heads/master", headers=headers, timeout=180)
                zresp.raise_for_status()
                zip_bytes = zresp.content

            for file_index, file_info in enumerate(listing.get("files", []), start=1):
                rel_path = str(file_info.get("path") or "")
                if not rel_path:
                    continue
                load_progress.report_stage_fraction(
                    "download",
                    file_index - 1,
                    len(listing.get("files") or []),
                    f"Downloading {file_index}/{len(listing.get('files') or [])}: {rel_path[:60]}",
                )
                target = (repo_dir / rel_path).resolve()
                if not str(target).startswith(str(repo_dir.resolve())):
                    continue
                if target.exists() and target.stat().st_size > 0:
                    downloaded.append(str(target))
                    repo_bytes += target.stat().st_size
                    continue
                zip_member_name = str(file_info.get("zip_member") or "")
                if zip_member_name and zip_bytes is not None:
                    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(zf.read(zip_member_name))
                    downloaded.append(str(target))
                    repo_bytes += target.stat().st_size
                    continue
                raw_url = f"https://raw.githubusercontent.com/{owner_repo}/HEAD/{quote(rel_path)}"
                resp = requests.get(raw_url, headers=headers, timeout=90)
                if resp.status_code != 200 or not resp.content:
                    items.append({"ok": False, "repo": owner_repo, "path": rel_path, "error": f"HTTP {resp.status_code}"})
                    failed += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(resp.content)
                downloaded.append(str(target))
                repo_bytes += len(resp.content)

            remaining_paths.extend(downloaded)
            total_bytes += repo_bytes
            items.append(
                {
                    "ok": True,
                    "repo": repo_url,
                    "files_selected": len(downloaded),
                    "bytes": repo_bytes,
                    "mb": _bytes_to_mb(repo_bytes),
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                }
            )
        except Exception as ex:
            failed += 1
            items.append({"ok": False, "repo": repo_url, "error": str(ex)})

    result: dict[str, Any] = {"ingested": 0, "failed": 0, "items": []}
    load_progress.stage("digest", f"Downloaded {len(remaining_paths)} file(s) — digesting into the knowledge library...")
    if remaining_paths:
        result = ingest_files(remaining_paths, metadata=_field_metadata(resolved), allow_embeddings=True)
        ingested = int(result.get("ingested") or 0)
        failed += int(result.get("failed") or 0)

    _note_last_ingest(resolved["field_slug"])
    return {
        "ok": ingested > 0 or (failed == 0 and bool(remaining_paths)),
        "field": resolved["field_name"],
        "field_slug": resolved["field_slug"],
        "domain": resolved["domain_slug"],
        "repos": [str(u or "").strip() for u in repo_urls if str(u or "").strip()],
        "files_downloaded": len(remaining_paths),
        "bytes_downloaded": total_bytes,
        "mb_downloaded": _bytes_to_mb(total_bytes),
        "ingested": ingested,
        "failed": failed,
        "items": items,
        "status": get_sentinel_status(refresh_counts=False),
    }


def ingest_huggingface_dataset_to_field(
    field: str,
    dataset: str,
    *,
    config_name: str = "default",
    split: str = "train",
    rows: int = 50,
) -> dict[str, Any]:
    """Download Hugging Face dataset rows and ingest them into a Sentinel field."""
    import json as _json

    from urllib.parse import quote as _quote

    import requests as _requests

    resolved = _resolve_field(field)
    dataset = str(dataset or "").strip()
    if not dataset:
        raise ValueError("Hugging Face dataset name is required.")
    config_name = str(config_name or "default").strip() or "default"
    split = str(split or "train").strip() or "train"
    limit = max(1, min(500, int(rows or 50)))

    url = (
        "https://datasets-server.huggingface.co/rows"
        f"?dataset={_quote(dataset, safe='')}&config={_quote(config_name, safe='')}"
        f"&split={_quote(split, safe='')}&offset=0&length={limit}"
    )
    load_progress.stage("download", f"Fetching {dataset} rows from Hugging Face...")
    resp = _requests.get(url, timeout=90, headers={"User-Agent": "SMi-Sentinel/1.0"})
    resp.raise_for_status()
    payload = resp.json()
    rows_payload = payload.get("rows") if isinstance(payload, dict) else []
    if not isinstance(rows_payload, list):
        rows_payload = []

    target_root = resolved["target_dir"]
    target_root.mkdir(parents=True, exist_ok=True)
    safe_name = "-".join(s for s in (dataset.replace("/", "-"), config_name, split) if s)
    path = target_root / f"hf-{safe_name}-{limit}.jsonl"
    written = 0
    with path.open("w", encoding="utf-8") as handle:
        for item in rows_payload[:limit]:
            row = item.get("row") if isinstance(item, dict) else item
            handle.write(_json.dumps(row, ensure_ascii=False) + "\n")
            written += 1
    if written <= 0:
        return {
            "ok": False,
            "field": resolved["field_name"],
            "field_slug": resolved["field_slug"],
            "dataset": dataset,
            "rows_selected": 0,
            "ingested": 0,
            "failed": 0,
            "items": [{"ok": False, "dataset": dataset, "error": "No rows returned by the Hugging Face datasets server."}],
            "status": get_sentinel_status(refresh_counts=False),
        }

    from .ingestion import ingest_files

    load_progress.stage("digest", f"Rows saved ({written}) — digesting into the knowledge library...")
    result = ingest_files([str(path)], metadata=_field_metadata(resolved), allow_embeddings=True)
    ingested = int(result.get("ingested") or 0)
    _note_last_ingest(resolved["field_slug"])
    return {
        "ok": ingested > 0,
        "field": resolved["field_name"],
        "field_slug": resolved["field_slug"],
        "domain": resolved["domain_slug"],
        "dataset": dataset,
        "config_name": config_name,
        "split": split,
        "rows_selected": written,
        "ingested": ingested,
        "failed": int(result.get("failed") or 0),
        "items": result.get("items") or [],
        "status": get_sentinel_status(refresh_counts=False),
    }


def remove_sentinel_field_data(field: str) -> dict[str, Any]:
    """Remove all documents attached to a field (purge its data room)."""
    from .db import library_connection

    resolved = _resolve_field(field)
    field_slug = resolved["field_slug"]
    removed_documents = 0
    removed_chunks = 0
    with library_connection("gemma") as conn:
        doc_ids = [
            int(row["id"])
            for row in conn.execute("SELECT id FROM documents WHERE scientific_field = ?;", (field_slug,)).fetchall()
        ]
        if doc_ids:
            placeholders = ",".join("?" for _ in doc_ids)
            removed_chunks = int(
                conn.execute(f"SELECT COUNT(1) AS n FROM chunks WHERE document_id IN ({placeholders});", doc_ids).fetchone()["n"]
            )
            conn.execute(f"DELETE FROM chunks WHERE document_id IN ({placeholders});", doc_ids)
            conn.execute(f"DELETE FROM chunk_fts WHERE document_id IN ({placeholders});", doc_ids)
            conn.execute(f"DELETE FROM documents WHERE id IN ({placeholders});", doc_ids)
            removed_documents = len(doc_ids)
        _refresh_field_counts(conn)
        conn.execute("UPDATE sentinel_scientific_fields SET last_ingest_at = NULL WHERE field_slug = ?;", (field_slug,))
        conn.commit()

    data_root = resolved["target_dir"] / "github"
    if data_root.exists():
        shutil.rmtree(data_root, ignore_errors=True)

    return {
        "ok": True,
        "field": resolved["field_name"],
        "field_slug": field_slug,
        "removed_documents": removed_documents,
        "removed_chunks": removed_chunks,
        "status": get_sentinel_status(refresh_counts=False),
    }
