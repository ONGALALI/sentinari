from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from .config import get_settings


def _memory_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else get_settings()
    memory = source.get("memory", {}) if isinstance(source.get("memory"), dict) else {}
    return {
        "session_summary_enabled": bool(memory.get("session_summary_enabled", True)),
        "session_summary_max_chars": max(400, min(4000, int(memory.get("session_summary_max_chars") or 1600))),
        "session_recent_messages": max(6, min(40, int(memory.get("session_recent_messages") or 14))),
        "session_recent_max_chars": max(800, min(10000, int(memory.get("session_recent_max_chars") or 3200))),
        "session_summary_refresh_min_messages": max(
            2,
            min(20, int(memory.get("session_summary_refresh_min_messages") or 4)),
        ),
        "session_history_api_limit": max(10, min(200, int(memory.get("session_history_api_limit") or 60))),
    }


def ensure_session_memory_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chat_session_memory (
            session_id TEXT PRIMARY KEY,
            rolling_summary TEXT NOT NULL DEFAULT '',
            last_compacted_message_id INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id_desc
            ON chat_messages(session_id, id DESC);
        """
    )


def _clip_text(text: str, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(0, max_chars - 3)].rstrip() + "..."


def _get_summary_row(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT rolling_summary, last_compacted_message_id, updated_at
        FROM chat_session_memory
        WHERE session_id = ?;
        """,
        (session_id,),
    ).fetchone()


def list_session_messages(conn: sqlite3.Connection, session_id: str, limit: int) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT id, role, content, citations_json, created_at
        FROM chat_messages
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT ?;
        """,
        (session_id, max(1, int(limit))),
    ).fetchall()
    return list(reversed(rows))


def _render_recent_messages(rows: list[sqlite3.Row], max_chars: int) -> str:
    lines: list[str] = []
    budget = 0
    for row in rows:
        role = str(row["role"] or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = _clip_text(str(row["content"] or ""), 260)
        if not content:
            continue
        line = f"{role}: {content}"
        budget += len(line)
        if budget > max_chars:
            break
        lines.append(line)
    return "\n".join(lines).strip()


def build_prompt_memory_block(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    settings: dict[str, Any] | None = None,
    recent_messages: int | None = None,
    recent_max_chars: int | None = None,
) -> str:
    memory_cfg = _memory_settings(settings)
    ensure_session_memory_schema(conn)

    recent_limit = recent_messages if recent_messages is not None else memory_cfg["session_recent_messages"]
    recent_chars = recent_max_chars if recent_max_chars is not None else memory_cfg["session_recent_max_chars"]
    summary_limit = memory_cfg["session_summary_max_chars"]

    summary_row = _get_summary_row(conn, session_id)
    recent_rows = list_session_messages(conn, session_id, recent_limit)
    recent_block = _render_recent_messages(recent_rows, recent_chars)

    sections: list[str] = []
    summary_text = ""
    if summary_row:
        summary_text = _clip_text(str(summary_row["rolling_summary"] or ""), summary_limit)
        if summary_text:
            sections.append("ROLLING SESSION MEMORY:\n" + summary_text)

    if recent_block:
        sections.append("RECENT SESSION TURNS:\n" + recent_block)

    return "\n\n".join(section for section in sections if section).strip()


def refresh_session_summary(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    ollama: Any | None,
    settings: dict[str, Any] | None = None,
) -> str:
    memory_cfg = _memory_settings(settings)
    ensure_session_memory_schema(conn)

    if not memory_cfg["session_summary_enabled"]:
        return ""

    totals = conn.execute(
        """
        SELECT COUNT(*) AS message_count, COALESCE(MAX(id), 0) AS last_message_id
        FROM chat_messages
        WHERE session_id = ?;
        """,
        (session_id,),
    ).fetchone()
    message_count = int(totals["message_count"] or 0)
    last_message_id = int(totals["last_message_id"] or 0)
    if message_count <= memory_cfg["session_recent_messages"] or last_message_id <= 0:
        return ""

    summary_row = _get_summary_row(conn, session_id)
    previous_summary = ""
    last_compacted_message_id = 0
    if summary_row:
        previous_summary = str(summary_row["rolling_summary"] or "").strip()
        last_compacted_message_id = int(summary_row["last_compacted_message_id"] or 0)

    new_message_count_row = conn.execute(
        """
        SELECT COUNT(*) AS new_message_count
        FROM chat_messages
        WHERE session_id = ? AND id > ?;
        """,
        (session_id, last_compacted_message_id),
    ).fetchone()
    new_message_count = int(new_message_count_row["new_message_count"] or 0)
    if previous_summary and new_message_count < memory_cfg["session_summary_refresh_min_messages"]:
        return previous_summary
    if ollama is None:
        return previous_summary

    new_rows = conn.execute(
        """
        SELECT role, content
        FROM chat_messages
        WHERE session_id = ? AND id > ?
        ORDER BY id ASC;
        """,
        (session_id, last_compacted_message_id),
    ).fetchall()
    if not new_rows:
        return previous_summary

    turn_lines: list[str] = []
    prompt_budget = 0
    for row in new_rows:
        role = str(row["role"] or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = _clip_text(str(row["content"] or ""), 320)
        if not content:
            continue
        line = f"{role}: {content}"
        prompt_budget += len(line)
        if prompt_budget > 4200:
            break
        turn_lines.append(line)
    if not turn_lines:
        return previous_summary

    summary_limit = memory_cfg["session_summary_max_chars"]
    system_prompt = (
        "You maintain SMi's persistent session memory.\n"
        "Return plain text only.\n"
        "Use exactly these headings:\n"
        "Stable facts:\n"
        "Open tasks:\n"
        "Decisions and constraints:\n"
        "Keep the memory concise, durable across reconnects, and under "
        f"{summary_limit} characters.\n"
        "Do not mention timestamps, citations, source IDs, or that this is a summary."
    )
    user_prompt = (
        f"Previous rolling memory:\n{previous_summary or '[none]'}\n\n"
        "New turns to absorb:\n"
        + "\n".join(turn_lines)
    )

    original_tokens = getattr(ollama, "max_output_tokens", None)
    try:
        if original_tokens is not None:
            ollama.max_output_tokens = max(120, min(int(original_tokens), max(180, summary_limit // 4)))
        summary_text = str(
            ollama.chat(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )
            or ""
        ).strip()
    except Exception:
        return previous_summary
    finally:
        if original_tokens is not None:
            ollama.max_output_tokens = original_tokens

    if not summary_text:
        return previous_summary

    cleaned_summary = _clip_text(summary_text.replace("```", ""), summary_limit)
    conn.execute(
        """
        INSERT INTO chat_session_memory (session_id, rolling_summary, last_compacted_message_id, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(session_id) DO UPDATE SET
            rolling_summary = excluded.rolling_summary,
            last_compacted_message_id = excluded.last_compacted_message_id,
            updated_at = excluded.updated_at;
        """,
        (session_id, cleaned_summary, last_message_id),
    )
    return cleaned_summary


def get_session_history(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    limit: int | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory_cfg = _memory_settings(settings)
    ensure_session_memory_schema(conn)
    fetch_limit = limit if limit is not None else memory_cfg["session_history_api_limit"]
    rows = list_session_messages(conn, session_id, fetch_limit)
    items: list[dict[str, Any]] = []
    for row in rows:
        citations: list[str] = []
        raw_citations = str(row["citations_json"] or "").strip()
        if raw_citations:
            try:
                parsed = json.loads(raw_citations)
                if isinstance(parsed, list):
                    citations = [str(item or "").strip() for item in parsed if str(item or "").strip()]
            except Exception:
                citations = []
        items.append(
            {
                "id": int(row["id"]),
                "role": str(row["role"] or "").strip().lower(),
                "content": str(row["content"] or ""),
                "created_at": str(row["created_at"] or ""),
                "citations": citations,
            }
        )

    summary_row = _get_summary_row(conn, session_id)
    return {
        "session_id": session_id,
        "count": len(items),
        "summary": str(summary_row["rolling_summary"] or "").strip() if summary_row else "",
        "summary_updated_at": str(summary_row["updated_at"] or "") if summary_row else "",
        "items": items,
    }


def get_session_history_readonly(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    limit: int | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory_cfg = _memory_settings(settings)
    fetch_limit = limit if limit is not None else memory_cfg["session_history_api_limit"]
    rows = list_session_messages(conn, session_id, fetch_limit)
    items: list[dict[str, Any]] = []
    for row in rows:
        citations: list[str] = []
        raw_citations = str(row["citations_json"] or "").strip()
        if raw_citations:
            try:
                parsed = json.loads(raw_citations)
                if isinstance(parsed, list):
                    citations = [str(item or "").strip() for item in parsed if str(item or "").strip()]
            except Exception:
                citations = []
        items.append(
            {
                "id": int(row["id"]),
                "role": str(row["role"] or "").strip().lower(),
                "content": str(row["content"] or ""),
                "created_at": str(row["created_at"] or ""),
                "citations": citations,
            }
        )
    try:
        summary_row = _get_summary_row(conn, session_id)
    except sqlite3.OperationalError:
        summary_row = None
    return {
        "session_id": session_id,
        "count": len(items),
        "summary": str(summary_row["rolling_summary"] or "").strip() if summary_row else "",
        "summary_updated_at": str(summary_row["updated_at"] or "") if summary_row else "",
        "items": items,
    }
