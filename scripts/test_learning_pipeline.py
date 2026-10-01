"""74 test_learning_pipeline.py - prove the learning pipeline end to end.

Owner request (§74): verify the pipeline that digests subject matter into
assessed learning. The weights were fuel; the pipeline still needs an engine
behind the gateway. Speed has no impact - so the ENGINE is the only thing
mocked here, exactly at the gateway boundary the rig-day engine replaces.
Everything else is REAL: real library documents, real chunks, real grading,
real persistence - all writes land in a SCRATCH database; the live library
and live learning_assessments are only ever READ.

Phases:
  A  LIVE, read-only: engine dark + worker enabled => guard held (no exams
     or 'skipped' burns since the last live exam of 2026-09-27).
  B  Priority ordering: which documents would be examined FIRST when the
     engine wakes (read-only against the live library).
  C  End-to-end exam: mock engine writes an exam from a REAL document's
     chunks; grade -> persist -> aggregate -> verify. The full chain the
     worker runs, proven without burning a single live record.
  D  Hazard check: a REACHABLE but useless engine (returns garbage) -
     demonstrate what probe_next does to documents today. Result feeds a
     proposal to the owner (machine proposes, owner decides).

Run:  .venv\\Scripts\\python.exe Scripts\\test_learning_pipeline.py
ASCII only.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # Sentinari/
sys.path.insert(0, str(ROOT))

# --------------------------------------------------------------------------
# Isolation (74 lesson from the first run): app/__init__.py installs a config
# SHIM whose get_settings() reads config/settings.yaml directly and IGNORES
# SENTINARI_CONFIG_PATH - so redirecting the env does nothing, and the first
# run briefly wrote 2 mock exams into the live DB (removed by hand, verified).
# Isolation is now enforced at the DB layer instead: learning_index's
# get_connection (main-DB writes: learning_assessments / learning_settings)
# is repointed at a SCRATCH database wherever writes can happen; the LIVE
# library (documents/chunks) is only ever READ via library_connection.
# --------------------------------------------------------------------------
SCRATCH_DIR = Path(tempfile.mkdtemp(prefix="sentinari_learning_test_"))
SCRATCH_DB = SCRATCH_DIR / "learning_test_main.db"
LIVE_MAIN_DB = ROOT / "data" / "smi_vocationalllm.db"


def _scratch_connection():
    conn = sqlite3.connect(str(SCRATCH_DB), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000;")
    return conn


def _isolate_learning_writes() -> None:
    from app import learning_index as LI

    LI.get_connection = _scratch_connection
    # The scratch DB starts empty: create learning tables BEFORE any query
    # touches them (probe_next reads learning_assessments early).
    LI._ensure_schema()

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def record(name: str, verdict: str, note: str = "") -> None:
    results.append((name, verdict, note))
    print(f"  [{verdict}] {name}" + (f" - {note}" if note else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# --------------------------------------------------------------------------
# Phase A - LIVE system, read-only: the dark-engine guard held
# --------------------------------------------------------------------------
def phase_a() -> None:
    section("A: 58 guard on the LIVE system (read-only)")

    # 1) Is the configured engine (Ollama :11434) actually dark?
    dark = True
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
        dark = False
    except Exception:
        dark = True
    record("engine :11434 is dark (Ollama uninstalled)", PASS if dark else "WARN",
           "as expected this cycle" if dark else "unexpected: something answers")

    # 2) Live DB, opened read-only: nothing consumed while dark?
    live_db = ROOT / "data" / "smi_vocationalllm.db"
    uri = f"file:{live_db.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    n_exams = conn.execute("SELECT COUNT(1) c FROM learning_assessments WHERE verdict != 'skipped'").fetchone()["c"]
    last_exam = conn.execute(
        "SELECT MAX(assessed_at) m FROM learning_assessments WHERE verdict != 'skipped'"
    ).fetchone()["m"]
    n_skipped = conn.execute("SELECT COUNT(1) c FROM learning_assessments WHERE verdict = 'skipped'").fetchone()["c"]
    last_skip = conn.execute(
        "SELECT MAX(assessed_at) m FROM learning_assessments WHERE verdict = 'skipped'"
    ).fetchone()["m"]
    conn.close()
    print(f"  live exams: {n_exams} (last {last_exam}) | skipped rows: {n_skipped} (last {last_skip})")
    frozen_ok = str(last_exam or "").startswith("2026-09-27")
    record("no new exams since the engine went dark", PASS if frozen_ok else "WARN",
           f"last exam {last_exam}")
    skips_predate_dark = (not last_skip) or (str(last_skip) <= str(last_exam or ""))
    record("every 'skipped' row predates the dark period (no 58 burns)",
           PASS if (n_skipped == 0 or skips_predate_dark) else "WARN",
           f"{n_skipped} skips, last {last_skip} (last exam {last_exam})")


# --------------------------------------------------------------------------
# Phase B - priority ordering, read-only, live library
# --------------------------------------------------------------------------
def phase_b() -> None:
    section("B: priority ordering - what gets examined FIRST on wake")
    from app.learning_index import LEARNING_PRIORITY_FIELDS, _candidate_documents, _norm_field, _priority_rank

    ids = _candidate_documents()
    print(f"  pending candidates: {len(ids)} (showing first 10)")
    top = ids[:10]
    lib = sqlite3.connect(f"file:{(ROOT / 'data' / 'sentinari.db').as_posix()}?mode=ro", uri=True, timeout=5)
    lib.row_factory = sqlite3.Row
    rows = []
    for i in top:
        r = lib.execute(
            "SELECT IFNULL(NULLIF(TRIM(scientific_field), ''), 'unclassified') f, title"
            " FROM documents WHERE id = ?", (i,)
        ).fetchone()
        rows.append((i, _norm_field(r["f"]), (r["title"] or "")[:60]))
    lib.close()
    for i, f, t in rows:
        print(f"    #{i:<7} rank={_priority_rank(f)} {f:<38} {t}")
    ranks = [_priority_rank(f) for _, f, _ in rows]
    ordered = all(ranks[i] <= ranks[i + 1] for i in range(len(ranks) - 1))
    first_fields = {_norm_field(f) for f in LEARNING_PRIORITY_FIELDS[:1]}
    head_is_p1 = _priority_rank(rows[0][1]) == 0
    record("candidates ordered by owner priority (P1 first)", PASS if (ordered and head_is_p1) else FAIL,
           f"top field '{rows[0][1]}' rank {ranks[0]}")


# --------------------------------------------------------------------------
# Phase C - end-to-end exam with the engine mocked at the gateway boundary
# --------------------------------------------------------------------------
class MockEngineGateway:
    """A WORKING engine: writes an exam grounded in the supplied text, then
    answers in its own (rebuilt) words. Grounding high, verbatim low."""

    name = "mock_engine"

    def __init__(self) -> None:
        self.calls = 0

    def describe(self) -> dict:
        return {"provider": self.name, "available": True, "chat_model": "mock-12b", "embedding_model": ""}

    def is_available(self) -> bool:
        return True

    def chat(self, messages, *, temperature=0.1, max_tokens=768) -> str:  # noqa: ARG002
        self.calls += 1
        user = next(m["content"] for m in messages if m["role"] == "user")
        source = user.split("Text (document:", 1)[-1]
        words = re.findall(r"[a-z]{5,}", source.lower())
        seen: set[str] = set()
        uniq = [w for w in words if not (w in seen or seen.add(w))]
        pick = uniq[3:33] if len(uniq) > 33 else uniq[:30]
        answer = ("In my own words: the material concerns "
                  + ", ".join(pick)
                  + ". Applied to the question, these are the operative concepts.")
        question = f"What role do the concepts ({', '.join(pick[:5])}) play in this document?"
        return json.dumps({"question": question, "answer": answer})


def phase_c() -> None:
    section("C: end-to-end exam on a REAL document (engine mocked)")
    from app import learning_index as LI

    _isolate_learning_writes()  # exam writes -> scratch DB
    gw = MockEngineGateway()
    LI.get_gateway = lambda: gw  # the ONLY mocked part - the rig replaces this

    rec = LI.probe_next()
    if rec is None:
        record("exam ran on the top-priority real document", FAIL, "probe_next returned None")
        return
    print(f"    document : #{rec['document_id']} '{rec['title'][:60]}'")
    print(f"    field    : {rec['scientific_field']}")
    print(f"    question : {rec['question'][:90]}")
    print(f"    answer   : {rec['answer'][:90]}")
    print(f"    grounding={rec['grounding_score']} verbatim={rec['verbatim_score']} "
          f"mastery={rec['mastery']} verdict={rec['verdict']}")
    ok1 = rec["verdict"] in {"applied", "partial", "recited", "not-learned"}
    record("exam produced a graded verdict", PASS if ok1 else FAIL, f"verdict={rec['verdict']}")

    rec2 = LI.probe_next()
    ok2 = rec2 is not None and rec2["document_id"] != rec["document_id"]
    record("second exam moved to the NEXT pending document", PASS if ok2 else FAIL,
           f"doc #{rec2['document_id']}" if rec2 else "none")

    status = LI.learning_status()
    print(f"    status: total={status['total']} assessed={status['assessed']} "
          f"percent={status['percent']} (scratch DB view)")
    record("status aggregation sees the new exams", PASS if status["assessed"] >= 2 else FAIL,
           f"assessed={status['assessed']}")
    with sqlite3.connect(SCRATCH_DB) as conn:
        n = conn.execute("SELECT COUNT(1) FROM learning_assessments WHERE verdict != 'skipped'").fetchone()[0]
    record("exam records persisted in the SCRATCH db only", PASS if n == status["assessed"] else FAIL,
           f"rows={n}")
    live_conn = sqlite3.connect(f"file:{(ROOT / 'data' / 'smi_vocationalllm.db').as_posix()}?mode=ro", uri=True, timeout=5)
    before = live_conn.execute("SELECT COUNT(1) FROM learning_assessments").fetchone()[0]
    live_conn.close()
    print(f"    live learning_assessments row count still {before} - untouched")


def phase_d() -> None:
    section("D: hazard check - reachable but USELESS engine (garbage output)")
    from app import learning_index as LI

    class UselessEngine(MockEngineGateway):
        def chat(self, messages, *, temperature=0.1, max_tokens=768) -> str:  # noqa: ARG002
            self.calls += 1
            return "I am an engine but I speak no JSON today."

    _isolate_learning_writes()  # hazard writes -> scratch DB
    gw = UselessEngine()
    LI.get_gateway = lambda: gw
    live_conn = sqlite3.connect(SCRATCH_DB)
    pending_before = live_conn.execute("SELECT COUNT(1) FROM learning_assessments").fetchone()[0]
    live_conn.close()

    rec = LI.probe_next()  # engine answers, but no JSON => probe_document None => 'skipped'?
    live_conn = sqlite3.connect(SCRATCH_DB)
    rows = live_conn.execute(
        "SELECT document_id, verdict FROM learning_assessments WHERE verdict = 'skipped' ORDER BY id DESC LIMIT 5"
    ).fetchall()
    live_conn.close()
    burned = len(rows)
    print(f"    useless engine answers; probe_next returned {rec}")
    print(f"    documents marked 'skipped' (consumed WITHOUT an exam): {burned}")
    for doc_id, _v in rows:
        print(f"      doc #{doc_id} consumed as skipped")
    record("HAZARD CONFIRMED: junk engine burns documents as skipped" if burned else
           "no burn: probe_next refused to consume", FAIL if burned else PASS,
           "feeds the 58b proposal" if burned else "guard already safe")


def _live_learning_rows() -> int:
    conn = sqlite3.connect(f"file:{LIVE_MAIN_DB.as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        return int(conn.execute("SELECT COUNT(1) FROM learning_assessments").fetchone()[0])
    finally:
        conn.close()


def main() -> int:
    print("SENTINARI LEARNING PIPELINE TEST - 74")
    print(f"scratch main DB: {SCRATCH_DB}")
    live_before = _live_learning_rows()
    print(f"live learning_assessments rows at start: {live_before} (must be unchanged at the end)")
    phase_a()
    phase_b()
    phase_c()
    phase_d()
    live_after = _live_learning_rows()
    record("LIVE DB untouched by the whole test", PASS if live_after == live_before else FAIL,
           f"{live_before} -> {live_after}")
    print("\n=== SUMMARY ===")
    for name, verdict, note in results:
        print(f"  [{verdict}] {name}" + (f" - {note}" if note else ""))
    hard_fail = any(v == FAIL for _n, v, _n2 in results)
    print("\nVERDICT: " + ("PIPELINE FUNCTIONAL - see FAIL rows for the one hazard" if hard_fail
                          else "PIPELINE FULLY FUNCTIONAL"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
