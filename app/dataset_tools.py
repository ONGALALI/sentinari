"""§80 — Dataset tool-gateway: let the LLM retrieve structured dataset facts.

Owner directive: "make it so that all the datasets can be retrieved by the
LLM." The chat pipeline already does semantic chunk retrieval (search_chunks)
and telemetry slices (_telemetry_block); what it cannot do today is answer
STRUCTURED questions about the library itself — how many documents per field,
what the biggest sources are, what the pattern store holds, what the
Assessment Matrix scores look like. This module is the open-book structured
layer: a small set of named, parameter-checked tool queries executed against
the library DB and pattern store, rendered as compact context blocks the chat
pipeline can attach to the LLM payload.

Design guardrails (open-book, not weights):
- Every tool is allow-listed by name; no free-form SQL from the model.
- Every tool takes a tiny, validated parameter set; LIKE patterns are
  parameterised (never string-interpolated).
- Reads only; busy-timeout capped so a mid-load writer cannot stall chat.
- Answers are compact (token-budgeted) and carry provenance (which table).
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from .db import library_connection

# ---------------------------------------------------------------------------
# Tool registry — each tool: name, description, params, runner
# ---------------------------------------------------------------------------

_TOOLS: dict[str, dict[str, Any]] = {}


def tool(name: str, description: str, params: dict[str, str]):
    def register(fn):
        _TOOLS[name] = {
            "name": name,
            "description": description,
            "params": params,
            "runner": fn,
        }
        return fn

    return register


def list_tools() -> list[dict[str, Any]]:
    return [
        {"name": t["name"], "description": t["description"], "params": t["params"]}
        for t in _TOOLS.values()
    ]


def _safe_like(value: str) -> str:
    """Escape LIKE wildcards in user/model-supplied patterns."""
    return str(value or "").replace("%", "").replace("_", " ").strip()[:80]


# ---------------------------------------------------------------------------
# Tool implementations (read-only, budgeted)
# ---------------------------------------------------------------------------


@tool(
    "dataset_overview",
    "Counts of documents and chunks per scientific field in the knowledge library.",
    {"field": "optional field name filter, e.g. physics"},
)
def tool_dataset_overview(field: str = "") -> dict[str, Any]:
    like = f"%{_safe_like(field)}%" if field else None
    with library_connection("gemma") as conn:
        if like:
            rows = conn.execute(
                """
                SELECT IFNULL(scientific_field, 'unassigned') AS field,
                       COUNT(1) AS docs
                FROM documents
                WHERE LOWER(IFNULL(scientific_field, '')) LIKE ?
                GROUP BY scientific_field ORDER BY docs DESC LIMIT 12
                """,
                (like,),
            ).fetchall()
            chunk_total = conn.execute(
                """
                SELECT COUNT(1) AS n FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE LOWER(IFNULL(d.scientific_field, '')) LIKE ?
                """,
                (like,),
            ).fetchone()["n"]
        else:
            rows = conn.execute(
                """
                SELECT IFNULL(scientific_field, 'unassigned') AS field, COUNT(1) AS docs
                FROM documents GROUP BY scientific_field ORDER BY docs DESC LIMIT 12
                """
            ).fetchall()
            chunk_total = conn.execute("SELECT COUNT(1) AS n FROM chunks").fetchone()["n"]
    return {
        "table": "documents+chunks",
        "fields": [{"field": r["field"], "documents": int(r["docs"])} for r in rows],
        "chunks_total": int(chunk_total),
    }


@tool(
    "top_sources",
    "Largest data sources (repos, datasets, works) in one field, by document count.",
    {"field": "scientific field slug, e.g. physics", "limit": "max rows (1-15, default 8)"},
)
def tool_top_sources(field: str = "", limit: int = 8) -> dict[str, Any]:
    limit = max(1, min(15, int(limit or 8)))
    like = f"%{_safe_like(field)}%"
    with library_connection("gemma") as conn:
        rows = conn.execute(
            """
            SELECT source_type, IFNULL(module, '') AS module, IFNULL(topic, '') AS topic,
                   IFNULL(source_url, '') AS url, COUNT(1) AS docs
            FROM documents
            WHERE LOWER(IFNULL(scientific_field, '')) LIKE ?
            GROUP BY source_type, module, topic, source_url
            ORDER BY docs DESC LIMIT ?
            """,
            (like, limit),
        ).fetchall()
    return {
        "table": "documents",
        "sources": [
            {
                "type": r["source_type"],
                "name": r["topic"] or r["module"] or "(unnamed)",
                "url": r["url"],
                "documents": int(r["docs"]),
            }
            for r in rows
        ],
    }


@tool(
    "field_catalog",
    "The scientific-field taxonomy: which fields exist, their domain, and their data volume.",
    {"domain": "optional domain filter, e.g. foundations-of-reality"},
)
def tool_field_catalog(domain: str = "") -> dict[str, Any]:
    like = f"%{_safe_like(domain)}%" if domain else None
    with library_connection("gemma") as conn:
        if like:
            rows = conn.execute(
                """
                SELECT domain_slug, field_name, field_slug, documents, chunks
                FROM sentinel_scientific_fields
                WHERE domain_slug LIKE ? ORDER BY documents DESC LIMIT 15
                """,
                (like,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT domain_slug, field_name, field_slug, documents, chunks
                FROM sentinel_scientific_fields ORDER BY documents DESC LIMIT 15
                """
            ).fetchall()
    return {
        "table": "sentinel_scientific_fields",
        "fields": [
            {
                "domain": r["domain_slug"],
                "field": r["field_name"],
                "documents": int(r["documents"] or 0),
                "chunks": int(r["chunks"] or 0),
            }
            for r in rows
        ],
    }


@tool(
    "dataset_facts",
    "Structured atomic facts (falsifiable claims + metrics + provenance) for a topic, from the Article V telemetry table.",
    {"topic": "topic keywords, e.g. receptor binding", "limit": "max facts (1-6, default 4)"},
)
def tool_dataset_facts(topic: str, limit: int = 4) -> dict[str, Any]:
    limit = max(1, min(6, int(limit or 4)))
    terms = [t for t in re.findall(r"[a-zA-Z]{4,}", _safe_like(topic).lower()) if t][:6]
    if not terms:
        return {"table": "article_v_knowledge", "facts": [], "note": "no usable topic terms"}
    like_clauses = " OR ".join("falsifiable_claims LIKE ?" for _ in terms)
    with library_connection("gemma", busy_timeout_ms=750) as conn:
        rows = conn.execute(
            f"""
            SELECT observation_id, scientific_field, falsifiable_claims,
                   numerical_metrics, epistemic_confidence, timestamp
            FROM article_v_knowledge
            WHERE ({like_clauses})
            ORDER BY epistemic_confidence DESC, timestamp DESC LIMIT ?
            """,
            (*[f"%{t}%" for t in terms], limit),
        ).fetchall()
    facts = []
    for r in rows:
        try:
            claims = json.loads(str(r["falsifiable_claims"] or "[]"))
        except Exception:
            claims = []
        if not claims:
            continue
        facts.append(
            {
                "field": r["scientific_field"],
                "claim": str(claims[0])[:280],
                "provenance": r["observation_id"],
                "confidence": float(r["epistemic_confidence"] or 0),
            }
        )
    return {"table": "article_v_knowledge", "facts": facts}


@tool(
    "pattern_store_summary",
    "What the pattern store currently holds: pattern counts by status, top patterns with confidence and fields.",
    {"status": "optional status filter (candidate/approved/testing/active/rejected)"},
)
def tool_pattern_store_summary(status: str = "") -> dict[str, Any]:
    from .pattern_store import _connect as _store_connect, ensure_pattern_store

    ensure_pattern_store()
    allowed = {"", "candidate", "approved", "testing", "active", "rejected"}
    status = status if str(status).lower() in allowed else ""
    with _store_connect() as conn:
        by_status = {
            r["status"]: int(r["n"])
            for r in conn.execute("SELECT status, COUNT(1) AS n FROM patterns GROUP BY status")
        }
        if status:
            rows = conn.execute(
                "SELECT id, title, pattern_type, confidence, status, fields_involved FROM patterns WHERE status = ? ORDER BY confidence DESC LIMIT 8",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, pattern_type, confidence, status, fields_involved FROM patterns ORDER BY confidence DESC LIMIT 8"
            ).fetchall()
    patterns = []
    for r in rows:
        try:
            fields = json.loads(str(r["fields_involved"] or "[]"))
        except Exception:
            fields = []
        patterns.append(
            {
                "id": int(r["id"]),
                "title": r["title"],
                "type": r["pattern_type"],
                "confidence": round(float(r["confidence"] or 0), 3),
                "status": r["status"],
                "fields": fields,
            }
        )
    return {"table": "patterns (patterns.db)", "by_status": by_status, "top_patterns": patterns}


@tool(
    "pattern_matrix_scores",
    "Assessment Matrix scores (SD_i% per dimension, NSIS) for one pattern id — computed by the math engine from its extraction record.",
    {"pattern_id": "numeric pattern id"},
)
def tool_pattern_matrix_scores(pattern_id: int) -> dict[str, Any]:
    from .assessment_math import DIMENSIONS, evaluate_pattern_matrix
    from .pattern_store import get_pattern, get_pattern_graph

    pattern = get_pattern(int(pattern_id))
    if pattern is None:
        return {"error": f"pattern {pattern_id} not found"}
    graph = get_pattern_graph(int(pattern_id))
    evaluation = evaluate_pattern_matrix(pattern, graph={"entities": 0, "relations": len(graph.get("relations") or [])})
    return {
        "table": "patterns.db + assessment_math engine",
        "pattern": {"id": int(pattern_id), "title": pattern.get("title")},
        "x_levels": evaluation["x_levels"],
        "nsis": evaluation["nsis"],
        "sd_percent": evaluation["sd_percent"],
        "level_bands": evaluation["level_bands"],
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_TOOL_CALL_RE = re.compile(r"\[\[(DATASET_TOOL)\s*:\s*([a-z_]+)\s*(?:\{([^}]*)\})?\s*\]\]", re.IGNORECASE)


def parse_tool_call(text: str):
    """Parse a [[DATASET_TOOL:name{json-args}]] request out of model text."""
    m = _TOOL_CALL_RE.search(str(text or ""))
    if not m:
        return None
    name = m.group(2).strip().lower()
    raw_args = (m.group(3) or "").strip()
    args: dict[str, Any] = {}
    if raw_args:
        try:
            args = json.loads(raw_args)
        except Exception:
            # tolerate key=value pairs
            for pair in re.findall(r"(\w+)\s*=\s*\"?([^,\"{}]+)\"?", raw_args):
                args[pair[0]] = pair[1].strip()
    return {"name": name, "args": args, "span": m.span()}


def run_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute an allow-listed tool; never raises."""
    tool_spec = _TOOLS.get(str(name or "").strip().lower())
    if tool_spec is None:
        return {"ok": False, "error": f"unknown tool '{name}'", "available": sorted(_TOOLS)}
    try:
        result = tool_spec["runner"](**(args or {}))
        return {"ok": True, "tool": tool_spec["name"], **result}
    except TypeError as ex:
        return {"ok": False, "tool": name, "error": f"bad arguments: {ex}", "params": tool_spec["params"]}
    except Exception as ex:
        return {"ok": False, "tool": name, "error": str(ex)[:200]}


def render_tool_result(result: dict[str, Any], max_chars: int = 1600) -> str:
    """Compact JSON block for the LLM payload (token-budgeted)."""
    try:
        text = json.dumps(result, ensure_ascii=False, indent=1, default=str)
    except Exception:
        text = str(result)
    if len(text) > max_chars:
        text = text[:max_chars] + " …(truncated)"
    return text


def build_tools_menu() -> str:
    """Prompt block telling the model which structured tools exist and how to
    request one. The chat pipeline appends this to LOCAL CONTEXT."""
    rows = "\n".join(
        f"- {t['name']}: {t['description']} params: {json.dumps(t['params'])}"
        for t in list_tools()
    )
    return (
        "STRUCTURED DATASET TOOLS — to fetch exact library facts, you may end your reply with a single "
        "tool request line (the system will run it and re-ask you with the result):\n"
        "[[DATASET_TOOL:tool_name{\"param\":\"value\"}]]\n"
        f"Available tools:\n{rows}\n"
        "Use tools for counts, rankings, catalog listings, structured facts, and matrix scores — "
        "never invent numbers about the library."
    )
