from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


VALID_TASK_STATUSES = {"pending", "in_progress", "completed", "blocked", "cancelled"}
LIVE_OPERATOR_STATE_KEY = "active"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any, *, max_length: int = 0) -> str:
    text = str(value or "").strip()
    if max_length > 0 and len(text) > max_length:
        return text[:max_length].rstrip()
    return text


def _task_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    attachment_raw = row["attachments_json"] if "attachments_json" in row.keys() else "[]"
    try:
        attachments = json.loads(str(attachment_raw or "[]"))
    except Exception:
        attachments = []
    normalized_attachments = _normalize_task_attachments(attachments)
    return {
        "id": int(row["id"]),
        "task_to_perform": str(row["task_to_perform"] or ""),
        "target_datetime": str(row["target_datetime"] or ""),
        "quality_standard_expected": str(row["quality_standard_expected"] or ""),
        "knowledge_library_applicable": str(row["knowledge_library_applicable"] or ""),
        "attachments": normalized_attachments,
        "attachment_count": len(normalized_attachments),
        "smi_feedback": str(row["smi_feedback"] or ""),
        "evaluation": str(row["evaluation"] or ""),
        "status": str(row["status"] or "pending"),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
        "last_smi_feedback_at": str(row["last_smi_feedback_at"] or ""),
    }


def list_tasks(conn: sqlite3.Connection, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM smi_tasks
        ORDER BY updated_at DESC, id DESC
        LIMIT ?;
        """,
        (max(1, int(limit)),),
    ).fetchall()
    return [_task_row_to_dict(row) for row in rows]


def get_task(conn: sqlite3.Connection, task_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM smi_tasks WHERE id = ?;", (int(task_id),)).fetchone()
    if row is None:
        return None
    return _task_row_to_dict(row)


def create_task(
    conn: sqlite3.Connection,
    *,
    task_to_perform: str,
    target_datetime: str = "",
    quality_standard_expected: str = "",
    knowledge_library_applicable: str = "",
    smi_feedback: str = "",
    evaluation: str = "",
    status: str = "pending",
) -> dict[str, Any]:
    status_value = str(status or "pending").strip().lower()
    if status_value not in VALID_TASK_STATUSES:
        status_value = "pending"
    now = _utc_now()
    conn.execute(
        """
        INSERT INTO smi_tasks (
            task_to_perform,
            target_datetime,
            quality_standard_expected,
            knowledge_library_applicable,
            attachments_json,
            smi_feedback,
            evaluation,
            status,
            created_at,
            updated_at,
            last_smi_feedback_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            _clean_text(task_to_perform, max_length=4000),
            _clean_text(target_datetime, max_length=80),
            _clean_text(quality_standard_expected, max_length=4000),
            _clean_text(knowledge_library_applicable, max_length=2000),
            "[]",
            _clean_text(smi_feedback, max_length=20000),
            _clean_text(evaluation, max_length=12000),
            status_value,
            now,
            now,
            now if str(smi_feedback or "").strip() else "",
        ),
    )
    task_id = int(conn.execute("SELECT last_insert_rowid() AS id;").fetchone()["id"])
    return get_task(conn, task_id) or {}


def update_task(
    conn: sqlite3.Connection,
    *,
    task_id: int,
    task_to_perform: str,
    target_datetime: str = "",
    quality_standard_expected: str = "",
    knowledge_library_applicable: str = "",
    smi_feedback: str = "",
    evaluation: str = "",
    status: str = "pending",
) -> dict[str, Any] | None:
    existing = get_task(conn, task_id)
    if existing is None:
        return None
    status_value = str(status or existing.get("status") or "pending").strip().lower()
    if status_value not in VALID_TASK_STATUSES:
        status_value = str(existing.get("status") or "pending")
    now = _utc_now()
    last_feedback_at = str(existing.get("last_smi_feedback_at") or "")
    if _clean_text(smi_feedback, max_length=20000) != str(existing.get("smi_feedback") or "").strip():
        last_feedback_at = now if str(smi_feedback or "").strip() else last_feedback_at
    conn.execute(
        """
        UPDATE smi_tasks
        SET task_to_perform = ?,
            target_datetime = ?,
            quality_standard_expected = ?,
            knowledge_library_applicable = ?,
            smi_feedback = ?,
            evaluation = ?,
            status = ?,
            updated_at = ?,
            last_smi_feedback_at = ?
        WHERE id = ?;
        """,
        (
            _clean_text(task_to_perform, max_length=4000),
            _clean_text(target_datetime, max_length=80),
            _clean_text(quality_standard_expected, max_length=4000),
            _clean_text(knowledge_library_applicable, max_length=2000),
            _clean_text(smi_feedback, max_length=20000),
            _clean_text(evaluation, max_length=12000),
            status_value,
            now,
            last_feedback_at,
            int(task_id),
        ),
    )
    return get_task(conn, task_id)


def update_task_feedback(
    conn: sqlite3.Connection,
    *,
    task_id: int,
    smi_feedback: str,
    status: str | None = None,
) -> dict[str, Any] | None:
    existing = get_task(conn, task_id)
    if existing is None:
        return None
    status_value = str(status or existing.get("status") or "pending").strip().lower()
    if status_value not in VALID_TASK_STATUSES:
        status_value = str(existing.get("status") or "pending")
    now = _utc_now()
    conn.execute(
        """
        UPDATE smi_tasks
        SET smi_feedback = ?,
            status = ?,
            updated_at = ?,
            last_smi_feedback_at = ?
        WHERE id = ?;
        """,
        (
            _clean_text(smi_feedback, max_length=20000),
            status_value,
            now,
            now,
            int(task_id),
        ),
    )
    return get_task(conn, task_id)


def build_task_prompt(task: dict[str, Any]) -> str:
    attachments = _normalize_task_attachments(task.get("attachments"), max_items=12)
    lines = [
        "Use the structured task record below as the user's instruction.",
        "Return concise, practical output targeted at completion, risk control, and quality.",
        "If the task cannot be fully completed from current context, state the blocker and the smallest next action.",
        "",
        f"Task to perform: {task.get('task_to_perform') or ''}",
        f"Target time/date: {task.get('target_datetime') or '[not set]'}",
        f"Quality standard expected: {task.get('quality_standard_expected') or '[not set]'}",
        f"Knowledge library applicable: {task.get('knowledge_library_applicable') or '[not set]'}",
    ]
    if attachments:
        lines.append("Attached task documents:")
        for item in attachments:
            label = (
                str(item.get("title") or "").strip()
                or str(item.get("original_name") or "").strip()
                or str(item.get("stored_name") or "").strip()
                or "document"
            )
            details: list[str] = []
            if item.get("document_id") is not None:
                details.append(f"document_id={item.get('document_id')}")
            if item.get("source_id"):
                details.append(f"source_id={item.get('source_id')}")
            suffix = f" ({', '.join(details)})" if details else ""
            lines.append(f"- {label}{suffix}")
    else:
        lines.append("Attached task documents: [none]")
    lines.extend(
        [
            f"Prior SMi feedback: {task.get('smi_feedback') or '[none]'}",
            f"User evaluation: {task.get('evaluation') or '[none]'}",
            "",
            "Respond with:",
            "1. Immediate interpretation of the task.",
            "2. Best next action or completed guidance.",
            "3. Risks or missing information.",
            "4. Short completion note suitable for the SMi feedback column.",
        ]
    )
    return "\n".join(lines).strip()


def _normalize_text_list(values: Any, *, max_items: int = 40, max_length: int = 500) -> list[str]:
    raw = values if isinstance(values, list) else []
    items: list[str] = []
    seen: set[str] = set()
    for item in raw:
        cleaned = _clean_text(item, max_length=max_length)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        items.append(cleaned)
        seen.add(key)
        if len(items) >= max(1, int(max_items)):
            break
    return items


def _normalize_task_attachments(values: Any, *, max_items: int = 50) -> list[dict[str, Any]]:
    raw = values if isinstance(values, list) else []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        stored_path = _clean_text(entry.get("stored_path"), max_length=4000)
        original_name = _clean_text(entry.get("original_name"), max_length=240)
        stored_name = _clean_text(entry.get("stored_name"), max_length=240)
        title = _clean_text(entry.get("title"), max_length=400)
        source_id = _clean_text(entry.get("source_id"), max_length=240)
        key = (stored_path or source_id or original_name or stored_name).lower()
        if not key or key in seen:
            continue
        document_id = entry.get("document_id")
        chunk_count = entry.get("chunk_count")
        byte_count = entry.get("bytes")
        items.append(
            {
                "original_name": original_name,
                "stored_name": stored_name,
                "stored_path": stored_path,
                "title": title,
                "source_id": source_id,
                "document_id": int(document_id) if isinstance(document_id, (int, float)) and document_id is not None else None,
                "chunk_count": int(chunk_count) if isinstance(chunk_count, (int, float)) and chunk_count is not None else 0,
                "bytes": int(byte_count) if isinstance(byte_count, (int, float)) and byte_count is not None else 0,
                "uploaded_at": _clean_text(entry.get("uploaded_at"), max_length=80),
            }
        )
        seen.add(key)
        if len(items) >= max(1, int(max_items)):
            break
    return items


def update_task_attachments(
    conn: sqlite3.Connection,
    *,
    task_id: int,
    attachments: list[dict[str, Any]],
    replace: bool = False,
) -> dict[str, Any] | None:
    existing = get_task(conn, task_id)
    if existing is None:
        return None
    existing_items = [] if replace else _normalize_task_attachments(existing.get("attachments"), max_items=50)
    merged = _normalize_task_attachments(existing_items + (attachments or []), max_items=50)
    conn.execute(
        """
        UPDATE smi_tasks
        SET attachments_json = ?,
            updated_at = ?
        WHERE id = ?;
        """,
        (
            json.dumps(merged, ensure_ascii=True),
            _utc_now(),
            int(task_id),
        ),
    )
    return get_task(conn, task_id)


def _state_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    try:
        supported_languages = json.loads(str(row["supported_languages_json"] or "[]"))
    except Exception:
        supported_languages = []
    if not isinstance(supported_languages, list):
        supported_languages = []

    try:
        goals = json.loads(str(row["goals_json"] or "[]"))
    except Exception:
        goals = []
    if not isinstance(goals, list):
        goals = []

    try:
        personality = json.loads(str(row["personality_json"] or "{}"))
    except Exception:
        personality = {}
    if not isinstance(personality, dict):
        personality = {}

    try:
        safety = json.loads(str(row["safety_json"] or "{}"))
    except Exception:
        safety = {}
    if not isinstance(safety, dict):
        safety = {}

    personality["name"] = str(personality.get("name") or row["name"] or "")
    personality["tone"] = str(personality.get("tone") or row["tone"] or "")
    personality["purpose"] = str(personality.get("purpose") or row["purpose"] or "")
    personality["default_language"] = str(personality.get("default_language") or row["default_language"] or "")
    if isinstance(personality.get("supported_languages"), list):
        personality["supported_languages"] = [str(x).strip() for x in personality.get("supported_languages", []) if str(x).strip()]
    else:
        personality["supported_languages"] = [str(x).strip() for x in supported_languages if str(x).strip()]
    personality["domain_focus"] = str(personality.get("domain_focus") or row["domain_focus"] or "")
    personality["out_of_scope_policy"] = str(personality.get("out_of_scope_policy") or row["out_of_scope_policy"] or "")
    if isinstance(personality.get("goals"), list):
        personality["goals"] = [str(x).strip() for x in personality.get("goals", []) if str(x).strip()]
    else:
        personality["goals"] = [str(x).strip() for x in goals if str(x).strip()]
    personality["general_addendum"] = str(
        personality.get("general_addendum")
        if personality.get("general_addendum") is not None
        else (row["general_addendum"] if row["general_addendum"] is not None else "")
    )
    personality["coding_mode_system_addendum"] = str(
        personality.get("coding_mode_system_addendum")
        if personality.get("coding_mode_system_addendum") is not None
        else (row["coding_mode_system_addendum"] if row["coding_mode_system_addendum"] is not None else "")
    )

    return {
        "state_key": str(row["state_key"] or LIVE_OPERATOR_STATE_KEY),
        "last_saved_source": str(row["last_saved_source"] or "manual"),
        "updated_at": str(row["updated_at"] or ""),
        "supported_languages": personality["supported_languages"],
        "goals": personality["goals"],
        "personality": personality,
        "safety": safety,
    }


def get_live_operator_state(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT *
        FROM smi_operator_state
        WHERE state_key = ?;
        """,
        (LIVE_OPERATOR_STATE_KEY,),
    ).fetchone()
    if row is None:
        return None
    return _state_row_to_dict(row)


def upsert_live_operator_state(
    conn: sqlite3.Connection,
    settings: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    personality = settings.get("personality", {}) if isinstance(settings.get("personality"), dict) else {}
    safety = settings.get("safety", {}) if isinstance(settings.get("safety"), dict) else {}
    supported_languages = _normalize_text_list(personality.get("supported_languages"), max_items=24, max_length=80)
    goals = _normalize_text_list(personality.get("goals"), max_items=40, max_length=2000)
    now = _utc_now()
    personality_json = json.dumps(personality, ensure_ascii=True)
    safety_json = json.dumps(safety, ensure_ascii=True)

    conn.execute(
        """
        INSERT INTO smi_operator_state (
            state_key,
            last_saved_source,
            name,
            tone,
            purpose,
            default_language,
            supported_languages_json,
            domain_focus,
            out_of_scope_policy,
            goals_json,
            general_addendum,
            coding_mode_system_addendum,
            personality_json,
            safety_json,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(state_key) DO UPDATE SET
            last_saved_source = excluded.last_saved_source,
            name = excluded.name,
            tone = excluded.tone,
            purpose = excluded.purpose,
            default_language = excluded.default_language,
            supported_languages_json = excluded.supported_languages_json,
            domain_focus = excluded.domain_focus,
            out_of_scope_policy = excluded.out_of_scope_policy,
            goals_json = excluded.goals_json,
            general_addendum = excluded.general_addendum,
            coding_mode_system_addendum = excluded.coding_mode_system_addendum,
            personality_json = excluded.personality_json,
            safety_json = excluded.safety_json,
            updated_at = excluded.updated_at;
        """,
        (
            LIVE_OPERATOR_STATE_KEY,
            _clean_text(source, max_length=80) or "manual",
            _clean_text(personality.get("name"), max_length=200),
            _clean_text(personality.get("tone"), max_length=4000),
            _clean_text(personality.get("purpose"), max_length=24000),
            _clean_text(personality.get("default_language"), max_length=60),
            json.dumps(supported_languages, ensure_ascii=True),
            _clean_text(personality.get("domain_focus"), max_length=12000),
            _clean_text(personality.get("out_of_scope_policy"), max_length=12000),
            json.dumps(goals, ensure_ascii=True),
            _clean_text(personality.get("general_addendum"), max_length=24000),
            _clean_text(personality.get("coding_mode_system_addendum"), max_length=24000),
            personality_json,
            safety_json,
            now,
        ),
    )
    return get_live_operator_state(conn) or {}


def ensure_live_operator_state(
    conn: sqlite3.Connection,
    settings: dict[str, Any],
    *,
    source: str = "startup_seed",
) -> dict[str, Any]:
    existing = get_live_operator_state(conn)
    if existing is not None:
        return existing
    return upsert_live_operator_state(conn, settings, source=source)


def snapshot_profile_settings(conn: sqlite3.Connection, settings: dict[str, Any], *, source: str) -> int:
    personality = settings.get("personality", {}) if isinstance(settings.get("personality"), dict) else {}
    safety = settings.get("safety", {}) if isinstance(settings.get("safety"), dict) else {}
    addendums = {
        "general_addendum": str(personality.get("general_addendum") or ""),
        "coding_mode_system_addendum": str(personality.get("coding_mode_system_addendum") or ""),
    }
    conn.execute(
        """
        INSERT INTO smi_profile_snapshots (
            source,
            purpose,
            domain_focus,
            out_of_scope_policy,
            goals_json,
            personality_json,
            safety_json,
            addendums_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            _clean_text(source, max_length=80) or "manual",
            _clean_text(personality.get("purpose"), max_length=24000),
            _clean_text(personality.get("domain_focus"), max_length=12000),
            _clean_text(personality.get("out_of_scope_policy"), max_length=12000),
            json.dumps(_normalize_text_list(personality.get("goals"), max_items=40, max_length=2000), ensure_ascii=True),
            json.dumps(personality, ensure_ascii=True),
            json.dumps(safety, ensure_ascii=True),
            json.dumps(addendums, ensure_ascii=True),
            _utc_now(),
        ),
    )
    row = conn.execute("SELECT last_insert_rowid() AS id;").fetchone()
    return int(row["id"])


def list_profile_snapshots(conn: sqlite3.Connection, *, limit: int = 12) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, source, purpose, domain_focus, out_of_scope_policy, goals_json, addendums_json, created_at
        FROM smi_profile_snapshots
        ORDER BY created_at DESC, id DESC
        LIMIT ?;
        """,
        (max(1, int(limit)),),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            goals = json.loads(str(row["goals_json"] or "[]"))
        except Exception:
            goals = []
        try:
            addendums = json.loads(str(row["addendums_json"] or "{}"))
        except Exception:
            addendums = {}
        items.append(
            {
                "id": int(row["id"]),
                "source": str(row["source"] or ""),
                "purpose": str(row["purpose"] or ""),
                "domain_focus": str(row["domain_focus"] or ""),
                "out_of_scope_policy": str(row["out_of_scope_policy"] or ""),
                "goals": goals if isinstance(goals, list) else [],
                "addendums": addendums if isinstance(addendums, dict) else {},
                "created_at": str(row["created_at"] or ""),
            }
        )
    return items


def record_qualia_history(
    conn: sqlite3.Connection,
    *,
    run_type: str,
    source: str,
    session_id: str = "",
    behavior_variant: float | None = None,
    effective_variant_ratio: float | None = None,
    gamma_requested: float | None = None,
    gamma_effective: float | None = None,
    stability_bias: float | None = None,
    stability_index: float | None = None,
    influence: float | None = None,
    attention_score: float | None = None,
    reasoning_score: float | None = None,
    logic_score: float | None = None,
    confidence: float | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    recommendation: dict[str, Any] | None = None,
    benchmark_summary: dict[str, Any] | None = None,
    bell_curve: dict[str, Any] | None = None,
    trajectory: list[dict[str, Any]] | list[Any] | None = None,
) -> int:
    conn.execute(
        """
        INSERT INTO qualia_history (
            run_type,
            source,
            session_id,
            behavior_variant,
            effective_variant_ratio,
            gamma_requested,
            gamma_effective,
            stability_bias,
            stability_index,
            influence,
            attention_score,
            reasoning_score,
            logic_score,
            confidence,
            before_state_json,
            after_state_json,
            recommendation_json,
            benchmark_summary_json,
            bell_curve_json,
            trajectory_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            _clean_text(run_type, max_length=40),
            _clean_text(source, max_length=80),
            _clean_text(session_id, max_length=120),
            behavior_variant,
            effective_variant_ratio,
            gamma_requested,
            gamma_effective,
            stability_bias,
            stability_index,
            influence,
            attention_score,
            reasoning_score,
            logic_score,
            confidence,
            json.dumps(before_state or {}, ensure_ascii=True),
            json.dumps(after_state or {}, ensure_ascii=True),
            json.dumps(recommendation or {}, ensure_ascii=True),
            json.dumps(benchmark_summary or {}, ensure_ascii=True),
            json.dumps(bell_curve or {}, ensure_ascii=True),
            json.dumps(trajectory or [], ensure_ascii=True),
            _utc_now(),
        ),
    )
    row = conn.execute("SELECT last_insert_rowid() AS id;").fetchone()
    return int(row["id"])


def list_qualia_history(conn: sqlite3.Connection, *, limit: int = 30) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM qualia_history
        ORDER BY created_at DESC, id DESC
        LIMIT ?;
        """,
        (max(1, int(limit)),),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        def _load_json(column: str, fallback: Any) -> Any:
            try:
                return json.loads(str(row[column] or json.dumps(fallback)))
            except Exception:
                return fallback

        items.append(
            {
                "id": int(row["id"]),
                "run_type": str(row["run_type"] or ""),
                "source": str(row["source"] or ""),
                "session_id": str(row["session_id"] or ""),
                "behavior_variant": row["behavior_variant"],
                "effective_variant_ratio": row["effective_variant_ratio"],
                "gamma_requested": row["gamma_requested"],
                "gamma_effective": row["gamma_effective"],
                "stability_bias": row["stability_bias"],
                "stability_index": row["stability_index"],
                "influence": row["influence"],
                "attention_score": row["attention_score"],
                "reasoning_score": row["reasoning_score"],
                "logic_score": row["logic_score"],
                "confidence": row["confidence"],
                "before_state": _load_json("before_state_json", {}),
                "after_state": _load_json("after_state_json", {}),
                "recommendation": _load_json("recommendation_json", {}),
                "benchmark_summary": _load_json("benchmark_summary_json", {}),
                "bell_curve": _load_json("bell_curve_json", {}),
                "trajectory": _load_json("trajectory_json", []),
                "created_at": str(row["created_at"] or ""),
            }
        )
    return items
