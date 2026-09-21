"""Export a blinded rater packet for the qr-v2 validation protocol.

Pulls assistant exchanges (question + answer + citations) from the live
database, stratified by reasoning_score quintile, and writes:

  data/validation/rater_packet_<N>.csv   (blinded: no index values, no session ids)
  data/validation/analysis_frame_<N>.csv (kept by PI: joined with index values)

Usage (from SMI_Core root):
  ../VocationalLLM/.venv314/Scripts/python.exe export_validation_sample.py [N_per_stratum]
"""
from __future__ import annotations

import csv
import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "smi_vocationalllm.db"
OUT_DIR = ROOT / "data" / "validation"

PER_STRATUM = int(sys.argv[1]) if len(sys.argv) > 1 else 20
SEED = 20260916  # fixed for reproducibility; log in protocol section 9 if changed


def main() -> int:
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT h.id,
                   h.session_id,
                   h.reasoning_score,
                   h.confidence,
                   h.recommendation_json,
                   h.created_at
              FROM qualia_history h
             WHERE h.run_type = 'recommendation'
               AND h.reasoning_score IS NOT NULL
             ORDER BY h.id
            """
        ).fetchall()

    candidates: list[dict] = []
    for row in rows:
        rec = json.loads(row["recommendation_json"] or "{}")
        focus = rec.get("focus_scores", {}) if isinstance(rec, dict) else {}
        # Exchange text is not stored in qualia_history; pull via session pairing.
        candidates.append(
            {
                "history_id": row["id"],
                "session_id": row["session_id"],
                "reasoning_index": float(row["reasoning_score"] or 0.0),
                "confidence": float(row["confidence"] or 0.0),
                "created_at": row["created_at"],
                "focus": focus,
            }
        )

    if not candidates:
        print("No recommendation rows with reasoning_score yet. Run some playground chats first.")
        return 1

    # Stratify by reasoning quintile
    candidates.sort(key=lambda c: c["reasoning_index"])
    strata = [candidates[i::5] for i in range(5)]
    sample: list[dict] = []
    for stratum in strata:
        take = min(PER_STRATUM, len(stratum))
        sample.extend(rng.sample(stratum, take))
    rng.shuffle(sample)

    # Join chat text per session (nearest preceding user/assistant pair)
    blinded_rows: list[dict] = []
    analysis_rows: list[dict] = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        for position, item in enumerate(sample, start=1):
            q = a = ""
            citations: list[str] = []
            if item["session_id"]:
                msgs = conn.execute(
                    """
                    SELECT role, content, citations_json, created_at
                      FROM chat_messages
                     WHERE session_id = ?
                     ORDER BY id
                    """,
                    (item["session_id"],),
                ).fetchall()
                # take messages closest in time to the history entry
                target = item["created_at"]
                user_msgs = [m for m in msgs if m["role"] == "user"]
                ai_msgs = [m for m in msgs if m["role"] == "assistant"]
                if user_msgs:
                    q = min(user_msgs, key=lambda m: abs(_ts_diff(m["created_at"], target)))["content"]
                if ai_msgs:
                    best = min(ai_msgs, key=lambda m: abs(_ts_diff(m["created_at"], target)))
                    a = best["content"]
                    try:
                        citations = json.loads(best["citations_json"] or "[]")
                    except Exception:
                        citations = []
            if not q.strip() or not a.strip() or len(a.split()) < 20:
                continue
            blinded_rows.append(
                {
                    "item_id": f"V-{position:03d}",
                    "question": q,
                    "answer": a,
                    "citations": "|".join(str(c) for c in citations),
                    "RQ_rater1": "",
                    "RQ_rater2": "",
                    "RQ_rater3": "",
                    "ED_rater1": "",
                    "ED_rater2": "",
                    "ED_rater3": "",
                }
            )
            analysis_rows.append(
                {
                    "item_id": f"V-{position:03d}",
                    "history_id": item["history_id"],
                    "reasoning_index": item["reasoning_index"],
                    "confidence": item["confidence"],
                    "answer_words": len(a.split()),
                    "citation_count": len(citations),
                    "grounding": item["focus"].get("grounding", ""),
                    "logic": item["focus"].get("logic", ""),
                    "anxiety": item["focus"].get("anxiety", ""),
                }
            )

    stamp = "final"
    blinded_path = OUT_DIR / f"rater_packet_{stamp}.csv"
    analysis_path = OUT_DIR / f"analysis_frame_{stamp}.csv"
    _write_csv(blinded_path, blinded_rows)
    _write_csv(analysis_path, analysis_rows)

    print(f"Packet: {blinded_path} ({len(blinded_rows)} items)")
    print(f"Frame:  {analysis_path} ({len(analysis_rows)} items)")
    print("Stratified reasoning quintiles:", [round(s['reasoning_index'], 3) for s in sample[:5]], "...")
    print("\nNext steps per VALIDATION_PROTOCOL.md:")
    print(" 1. Give rater_packet_final.csv to 3 blinded raters (rubric in protocol section 4).")
    print(" 2. Fill RQ_/ED_ columns, lock ratings, compute Kendall's W (need >= 0.60).")
    print(" 3. Join with analysis_frame_final.csv on item_id; compute Spearman rho (H1-H3).")
    return 0


def _ts_diff(a: str, b: str) -> float:
    from datetime import datetime, timezone

    def parse(value: str):
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    try:
        return abs((parse(a) - parse(b)).total_seconds())
    except Exception:
        return 1e18


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
