# SENTINEL — CONTINUITY LOG

_Last updated: 2026-09-19 ~01:30 SAST, written by **Buffy** (the Codebuff coding agent) so any future session — or any machine — can resume exactly where we stopped. The owner also keeps his own log; this file is the agent-side mirror. Read this file first, then `CREDITS.md`, before doing anything._

---

## 1. Project identity

- **Project:** Sentinel / SMi Autonomous Playground — `SMI_Core`, launched with `run_smi.py`, UI at `http://127.0.0.1:8099/ui/playground`.
- **Owner:** Inspirari (South Africa). Vision, architecture, and design docs are the owner's: **SENTINEL-v2.pdf** and **DOC-0 "The Constitution"** (uploaded into the Computer Science & AI field; they landed in the political-science folder; extracted text cached at `data/_sentinel_v2.txt`).
- **Mission (owner's words):** discover problems/critical issues impacting society (society **includes AI**) and provide solutions. Sentinel must **master pattern recognition** — new patterns should create new tables/fields automatically. Examples the owner gave: a paper on Cancer → actively seek cures; disease + medicine under Health → recognize, combine, list in a new table; Covid → cure; even "2 + 2 = 4" is a new pattern to populate.
- **Agent of record:** Buffy via Codebuff. Owner has kindly requested credits be kept visible (done — see §6).

## 2. Architecture decisions already made (do not re-litigate)

- **One shared LLM + RAG + a pattern layer above it — NOT an LLM per scientific field.** Cross-domain patterns are the whole point; per-field models would structurally prevent them. 21 fields cannot fit in 24 GB VRAM anyway.
- **Fine-tuning is deferred.** Sentinel's purpose is installed as identity + tools (system prompt + pattern store queries). If tuning ever happens: one light QLoRA on extraction format / evidence-citing style, never per field, and only after an eval harness exists.
- **Provider-agnostic LLM gateway** — the Ollama umbilical cord is cut (see §4).
- **The LLM proposes; the registry disposes.** Models never write schema directly; the template registry runs guarded migrations.

## 3. What is built and live-verified (dataset lane)

All in `app/` + `templates/playground_console.html`:

- **Scientific field Guardians** — spring-open accordion per field in the playground, each with its own sourcing worker panel.
- **Tri-source discovery** — `/api/skill-review/find` searches **GitHub + Hugging Face + OpenAlex simultaneously** (parallel threads) and merges results. Search string = **main field name only** ("Physics", not "quantum, relativity, …" — the sub-science widening was removed from `openalex_worker.py` per owner request). Live test with "Physics": 18 candidates (6 per source).
- **Candidate lifecycle** — Approve / Reject / Test / Load with color states, progress bars with % (Downloading → Digesting → "Ingested: N documents"), disabled after success. Load works **directly from stored candidate ID** (fixed "Stored candidate not found for ingest": the old save→re-lookup-by-URL flow missed).
- **Field routing hardened** — loose resolver in `sentinel_domains.py` maps any stored field spelling to the slug (the owner's exact error string resolves to `physics`) and heals stored rows (fixed "Unknown Sentinel scientific field").
- **Formats Gemma digests** — real PDFs (OpenAlex open-access), publisher landing-page HTML, OpenAlex metadata records (abstract + JSON), JSONL row dumps (HF), repo files from GitHub (.md/.txt/.csv/.py…). OpenAlex download chain: PDF → landing-page HTML → metadata record.
- **Permanent per-field loaded list** in each container (DB-backed, survives refresh/restart) with Preview (HTML modal) and Download (.pdf — real stored PDF when available, else generated via `app/text_pdf.py` on pypdf).
- **Reliability fixes** — `taxonomy.py` falls back to the main DB for `taxonomy_nodes` (library-scoped connections crashed); `_note_last_ingest` is best-effort with retry (SQLite busy locks vs the live server); `skill_review.py` status writes use a long busy timeout; `coding_corpus.py` skips empty/corrupt files as honest "skipped" (owner applauded this) — forced rescan: 85 processed, 0 failed.
- **OpenAlex keys:** the key in `app/apis/open-alex-api.md` is **rejected (401)**; the working key is URL-embedded in the root `.env` (`D:\inpirari\.env`). The loader tries candidates in order.

## 4. LLM gateway — the cord is cut

`app/llm_gateway.py`:

- Providers: **OllamaProvider, GeminiProvider, OpenAICompatibleProvider**; chosen by `config/settings.yaml` → `llm:` block. Currently `provider: ollama`, `fallback_providers: [gemini]`, `chat_model: gemma4:12B`, `embedding_model: nomic-embed-text`, `num_gpu: 0` (CPU-only on the laptop — slow).
- Reads `GEMINI_API_KEY` from the root `.env` as fallback. Gemini default model: **`gemini-flash-latest`** (rolling alias — `gemini-2.0-flash` is retired; thinking disabled for fast structured JSON).
- Retries transient 503s. API: `chat()`, `chat_json()`, `embed()`, `parse_json_loose()`, `get_gateway()`, `reset_gateway()`.
- **Proven:** with Ollama pointed at a dead port, the request fell through to Gemini and returned valid JSON.
- **To move to Google Cloud:** flip `provider: gemini` in `settings.yaml`. That is the entire software migration.

## 5. Pattern-Recognition MVP (the core, per the owner's mission)

- `app/pattern_store.py` → `data/patterns.db`: `pattern_entities`, `pattern_relations`, `patterns`, `pattern_evidence`, plus a **template registry with guarded auto-migrations** (new pattern types create their own tables). Every observation carries the Constitution's **Article V anatomy**: identity, source, timestamp, evidence, relationships, confidence, contradictions, evolution history, unresolved questions.
- `app/pattern_worker.py` — structured extraction through the gateway after ingest + cross-field synthesis proposals. (Note: template prompts use explicit keyword substitution — `{text}` is not a valid str.format key; already fixed.)
- `app/pattern_api.py` → `/api/patterns` endpoints (list, detail, analyze, review), registered in `app/main.py`. **Pattern Recognition Lab** card lives in the playground with the same Approve / Reject / Test lifecycle.
- 4 templates seeded: problem→solution, entity-relation, claim→evidence, cross-field convergence.
- **Live proof:** Gemini extraction from DOC-0 (Drafting the Constitution) → **11 entities, 8 relations, 5 candidate patterns**, evidence-chained, e.g. "Evidence-Driven Institutional Neutrality", "Epistemic Humility Through Systematic Self-Correction", "Withholding Judgment as Intellectual Honesty".

## 6. Credits (owner request — keep maintained)

- `SMI_Core/CREDITS.md` — full attribution record.
- Playground footer credit line in `templates/playground_console.html` (after the last `<script>`, before `#datasetPreviewModal`).

## 7. Environment / gotchas

- Windows box; terminal needs the `cd D:/inpirari/SMI_Core && …` form; bash availability has flaked mid-session before (retry; also `/dev/stdin` does not work with node on Windows — write temp files instead).
- pypdf 5.9 API: use `writer.add_blank_page()`; `_add_object` returns an `IndirectObject` directly (see `text_pdf.py`).
- The server runs from `SMI_Core` (verified via process inspection). A "Resonance Matrix NOT loaded" banner seen once was a stale-page artifact.
- Owner's pre-existing data (552 docs, `github/` folders) must never be touched; agent test artifacts are always cleaned after verification.
- Vector embeddings require Ollama up; text chunks always persist regardless.

## 8. Next steps (agreed, in order)

1. **Wire pattern extraction to run automatically after every successful ingest** (no manual trigger).
2. **Scheduled cross-field synthesis sweep** → proposes convergence patterns into the Lab queue.
3. **Auto-growing schema engine** — registry migrations with history + rollback.
4. **New-machine bootstrap** (machine incoming: 24 GB GPU AMD Ryzen 9, 84 GB RAM, 2 TB SSD; temporary box due to CPU failure on the old dev machine): install deps, copy `SMI_Core` data + `D:\inpirari\.env`, flip gateway to `gemini`-primary with `ollama` fallback (local gemma3 12B Q4 + embeddings fit comfortably), end-to-end smoke test of discovery → ingest → pattern extraction.
5. **Six-month milestone roadmap** (owner intends to fund 6 months of credits upfront once the machine lands).
6. OpenAlex: owner may paste the working key into `app/apis/open-alex-api.md` (cosmetic; loader already works).

## 9. Resume protocol for the next agent/session

1. Read this file + `CREDITS.md`; check `git status` and current branch (`etd.github.io` as of this log).
2. Start `run_smi.py`; confirm `/api/patterns` + `/api/skill-review/find` respond; confirm the playground footer/credits render.
3. Continue §8 from item 1 unless the owner redirects. Keep the owner's mission (§1) as the north star, verify everything live before claiming it, and clean up test artifacts.

— Buffy 🤖

---

## 10. 2026-09-19 (later): QWEN CODING AGENT REMOVED — playground 500s fixed

The owner reported internal server errors on the playground and requested that Qwen, the
"Coding Agent", be removed from SMi / Sentinel entirely (no value, adding confusion).

**Root causes found:** (a) `curriculum_quality_audit.db` was corrupt ("database disk image
is malformed") — `/api/playground/curriculum-audit/status` returned 500 on every poll;
(b) the Qwen Coding Agent stack was dead weight woven through the app.

**What was done (all verified live):**

1. **Data safety first** — everything preserved in `data/backups/2026-09-19-qwen-removal/`:
   DB copies + the deleted modules + `settings_qwen.yaml` + `scripts/migrate_library_split.py`
   + `coding_agent/adapter_agent.py` scripts.
2. **Qwen library migrated into Gemma library** (previous session): 4,981 docs / 179,677
   chunks now live in the single `library_gemma.db`; 12 loaded candidates repointed.
   Integrity verified `ok`; SENTINEL-v2 (doc 42) and both Constitution docs (729, 4980)
   confirmed present.
3. **Data layer collapsed to one library**: db.py UNION views → single library;
   library_router → gemma-only; ingestion/retrieval/firewall/skill_review/taxonomy repointed.
4. **Backend removed**: `app/coding_agent.py`, `coding_agent_training.py`, `coding_tunnel.py`,
   `curriculum_audit.py`, `autonomous_training_worker.py` deleted; `main.py` imports, router
   registration, startup/shutdown hooks, all `/api/playground/coding-agent/*`,
   `/api/playground/autonomous-training/*`, `/api/coding/escalate*`, persona toggle endpoints
   (`/api/playground/persona`, `/api/inpirari/persona*`), `/ui/coding-agent` removed;
   `CodingEscalationRequest` removed from models.py.
5. **UI removed**: the whole "Datasets — Teach SMi…" card (it WAS the coding-agent training
   card; GitHub/HF discovery now lives in each field's tri-source worker), sidebar/hero
   links, all related JS, the header auto-poll checkbox, and the Inpirari Start console's
   Qwen workspace card + persona toggle.
6. **Corrupt DB quarantined** — moved to backups; the feature had zero rows (never used).
7. **Orphaned files removed**: `gateway_API_Registry.py`, `gateway_plug.py` (truncated, never
   compiled), `routers/gemma_lab.py` (IndentationError, never imported).
8. **Config cleaned**: qwen models removed from firewall `allowed_chat_models`;
   `settings_qwen.yaml` deleted.
9. **Verification**: compileall OK; server boots on scratch port; `/health` green
   (startup_error empty, firewall ok); playground + start pages 200; every removed endpoint
   404; templates contain zero qwen references; JS syntax-checked with node.

**Note:** the "Datasets" removal is deliberate — the same GitHub/Hugging Face capability now
lives inside each scientific field's worker box (search + approve + load with progress bars).
If the owner ever wants a standalone document-upload lane again, it should be rebuilt on the
tri-source field pipeline, not the old Qwen library.

**Boot-test hygiene:** scratch-port uvicorn processes were fully stopped after each test;
port 8099 left free for the owner's normal `run_smi.py`.

---

## 11. Lean-Sentinel completion + Clear-candidates feature (2026-09-19, morning SAST)

### ETDP / curriculum / qualification removal — COMPLETE (three-app separation)
The owner confirmed: **ETDP, Curriculum, and Sentinel are three separate apps** that once
shared code for economy. All ETDP/curriculum/qualification traces are now gone from SMI_Core.

1. **Schema migration (applied to `data/library_gemma.db`, backup in
   `data/backups/2026-09-19-lean-schema/`)**:
   - `documents`: DROPPED `qualification`, `unit`, `learning_outcome`, `bloom_level`
     (ETDP-only, empty except 2 rows); RENAMED `curriculum_name` -> `source_collection`
     (it actually held source-collection labels: 'Quantum Physics', 'SMi Skills',
     'SMi Coding Corpus'). 27 -> 23 cols.
   - `ingest_events`: DROPPED `qualification`; RENAMED `curriculum_name` -> `source_collection`.
   - `module`/`topic` KEPT: the dataset workers repurposed them as source-lane
     ('github-repository', 'huggingface-dataset', ...) and item name.
   - `idx_documents_curriculum` replaced by `idx_documents_module_topic`.
   - Migration used `PRAGMA legacy_alter_table=ON` so the chunks FK stayed intact;
     integrity ok, 4,981 docs / 179,632 chunks / 7,937 events preserved.
2. **Code rename**: `curriculum_name` -> `source_collection` across db.py, ingestion,
   retrieval, conversation, playground, models, unsupervised, taxonomy
   (`CATEGORY_TO_COLUMN['curricula']` now maps to `source_collection`).
3. **Removed dead ETDP code**: `LessonSourceRequest`, `SMITrainingDatasetRequest`,
   `SummativeMemoranda*Request` models; `_record_lesson_content_event`,
   `_resolve_lesson_content_tuning`, `_build_quality_metrics` helpers;
   `lesson_content_events` table (schema + all refs); qualification filter plumbing in
   `search_chunks`/`run_chat`/PlaygroundChat; ETDP-flavored hint strings.
4. **Config shim**: `resolve_playground_learning_control` stub removed from `app/__init__.py`.
5. **Verification**: compileall OK, import OK (112 routes), boot on scratch port green,
   playground 200, skill-review 200, zero errors in log. Final sweep: **zero** etdp/qwen/
   curriculum/qualification/learning_outcome/bloom references in app/*.py.

### Clear-candidates feature (owner request: switch sciences cleanly)
- **Backend**: `POST /api/skill-review/candidates/clear?scientific_field=<field>`
  (empty field = clear all, guarded by confirm in UI). Deletes ONLY pending/approve/
  reject/test candidates — **loaded datasets are never touched**. Also
  `GET /api/skill-review/candidates` gained `scientific_field` filter (space-insensitive
  matching: "Computer Science" == "computer-science").
- **UI (playground)**:
  - "Clear Candidates" button next to Discover Candidates in the Discovery & Review
    panel; scoped to the field in the box, or ALL fields (confirm) when empty.
  - Per-field "Clear" button inside every Sentinel field's sourcing worker box
    (data-role="sourcing-clear") — wipes that field's candidates + local results panel.
  - The review panel lists candidates scoped to the field in the box, so Physics
    candidates no longer clutter a Chemistry search.
- **Button focus/hover feedback (owner request)**: global CSS — `button:hover`
  brightness, `button:focus-visible` amber outline + blue glow ring; all buttons app-wide.

### Next big milestone (owner, ~next week): TRUNCATE OLLAMA
The owner wants Ollama removed entirely if possible — a different LLM (not necessarily
Gemma) is acceptable. The `llm_gateway` + `config/settings.yaml` were built for exactly
this: switch `llm.provider` (gemini / openai-compatible / etc.) + key, keep the app code
untouched. Embeddings must move too (currently nomic-embed-text via Ollama) — decide
provider-side embeddings vs a small local fallback. Also review `llm_boundary.py`
(ollama autostart guard) and `conversation.py` direct Ollama paths.


---

## 12. Load-500 hotfix (2026-09-21, ~02:30 SAST)

**Symptom:** every "Load into field" from all three sources -> "Load failed: Internal server error".

**Root cause 1 (the killer):** `app/ingestion.py::_record_ingest_event` — when the lean
migration dropped `qualification` from `ingest_events`, the column list lost a name but
kept a `?`: 15 columns, 16 placeholders -> `sqlite3.OperationalError: 16 values for
15 columns` on EVERY ingestion. Found via the live traceback in
`logs/launch-smi-core.log`. One placeholder removed; fixed.

**Root cause 2:** main DB (`smi_vocationalllm.db`) `unsupervised_runs` still had
`curriculum_name` (lean rename was applied to code + `library_gemma.db` but missed the
main DB). `unsupervised.py` writes `source_collection` -> any unsupervised run would
have 500'd too. Renamed live (96 rows, metadata-only, integrity ok).

**Full-code INSERT audit (paren-aware):** every INSERT now balanced; all columns exist
in the actual schemas (datetime('now') literals cause benign scanner noise).

**Data safety:** the 500s happened inside transactions — **zero data loss, zero orphan
documents**. Statuses were: 9 approve / 12 loaded / 68 pending / 3 reject.

**Verified live on scratch port 8077:** the owner's four previously-failed candidates
loaded for real:
- 241, 244, 246 (OpenAlex papers) -> status=loaded, doc ids 4985-4987.
  Note: PMC returns 403 for direct PDF fetch; the worker falls back to the landing
  page and ingests that HTML — by design.
- 227 (GitHub patchy631/ai-engineering-hub) -> 200 files / 8.5 MB ingested, 0 failed.
- 231 (HF joey234/mmlu-...) -> 500 comes from HF's datasets-server itself for that
  dataset (upstream), surfaced transparently — not our bug.
Test server stopped; port 8099 free. Compile OK.

**Owner action:** restart run_smi.py (or it will pick ingestion.py up on restart) and
re-click Load on any candidate; approved-but-unloaded rows stay approved.

---

## 13. Live Load-progress feature (2026-09-21, morning SAST)

**Owner request:** real per-stage percentages (download / digest / embed) on Load, for
all three sources, driven by a backend progress endpoint.

### Built
- **`app/load_progress.py`** (new): thread-bound progress engine. Stage bands:
  download 2-50, digest 50-78, embed 78-98, finalize 98-100. In-memory job store
  (max 200 jobs, 400 events each). Module helpers (`stage`, `report_stage_fraction`,
  `embed_progress`, `emit`, `emit_meta`) are fire-and-forget no-ops without a bound
  job, so normal ingestion is untouched.
- **Endpoint changes (`app/skill_review.py`):** `POST /candidates/{id}/ingest` now
  starts a background job and returns `{job_id, async: true}` immediately;
  `GET /progress/{job_id}` returns live state/percent/stage/message; `?wait=1`
  preserves the old synchronous behaviour.
- **Instrumented:** GitHub per-file downloads, OpenAlex per-work fetches, HF fetch,
  per-file digest loop, per-chunk embedding loop.
- **Frontend (playground template):** Load button polls every 700 ms; the bar now
  shows the real stage + backend message ("Downloading 155/200: ...", "Embedding
  chunk 168/213..."). Survives 4 transient poll failures before erroring.

### Two real concurrency fixes discovered during verification
1. **Library busy timeout:** ingestion connections used the 1 s default; during
   startup digestion storms every statement fought the write queue (a load stalled
   40+ s after embedding). `ingest_files` now sets `PRAGMA busy_timeout = 30000` on
   its library connection.
2. **Ingestion serialisation:** two concurrent Loads starved each other statement-
   by-statement (SQLite = one writer). `ingest_files` now takes a process-level
   `_INGEST_WRITE_LOCK`; a second load reports "Waiting for another ingestion to
   finish..." and proceeds the moment the first completes.

### Verified live (scratch port 8077, during startup digestion storm)
- OpenAlex (243): 2 -> 50 -> done 100 in ~6 s, ingested 1.
- HuggingFace (201): per-chunk 8/31 ... 31/31 -> done, ingested 1.
- GitHub (193, psychopy, 200 files): per-file download 20/200... -> digest ->
  Embedding chunk 213/213 -> **done, ingested 200, failed 0**.
- Concurrent GH + HF loads: HF completed while GH ran (no starvation).
- Library integrity ok; 5,397 docs; 20 candidates loaded total. Test server stopped.

**Owner action:** restart run_smi.py + hard refresh (Ctrl+F5). Note: HF datasets
rejected by HF's own datasets-server fail fast with the upstream error shown.

---

## 14. Candidate dedupe + "Already loaded" badge (2026-09-21, midday SAST)

**Owner request:** prevent duplicate candidate datasets (and the server errors they
invite). Options offered: a visible badge, or automatic prevention. Delivered: BOTH,
with the database as the foundation.

### Built
- **Identity keys** (`_source_identity` in `app/skill_review.py`): one dataset = one
  identity regardless of URL shape — OpenAlex by DOI / W-id (so DOI link, landing
  page and PMC mirror collapse to one), GitHub by owner/repo (case- and .git-proof),
  HuggingFace by dataset id, anything else by normalized URL.
- **Schema (main DB, applied via `_ensure_schema` on first endpoint hit):** new
  `identity_key` column, one-time backfill (92 rows), legacy-duplicate collapse
  (never touches loaded/rejected rows), and a **partial UNIQUE index**
  (`idx_skill_review_identity`) making reviewable duplicates physically impossible.
  `_ensure_schema` now retries with a 30 s busy window so it survives startup
  digestion storms.
- **All three storage paths hardened** (`/find`, `/candidates/save`, `/discover`):
  existing rows are reused (review status preserved), loaded/rejected identities are
  never resurrected as fresh pending rows, and responses report
  `duplicates_skipped`. In-batch dedupe stops the same work appearing twice in one
  search response.
- **New endpoint** `GET /api/skill-review/loaded-identities` -> identity keys of all
  loaded datasets.
- **UI:** green **"Already loaded ✓"** badge on cards; Approve/Reject/Test disabled
  and Load replaced by "Loaded ✓" for already-loaded items; duplicate counts shown
  in search status; identity cache refreshed at startup and after every load.
- `/find` response items now carry `already_loaded` / `previously_rejected` flags.

### Verified live (scratch port 8077)
- Migration: column added, 92 rows backfilled, unique index created, data untouched
  (4 approve / 20 loaded / 65 pending / 3 reject).
- Two identical "engineering" searches: 24 found both times, 6 duplicates skipped,
  6 already-loaded flags — **row count 92 before AND after**.
- loaded-identities endpoint: 20 identities. Test server stopped.

**Owner action:** restart run_smi.py + hard refresh (Ctrl+F5); the migration applies
itself on the first candidates fetch.

---

## 15. Scientific Patterns Discovery workspace (2026-09-21, afternoon SAST)

**Owner request:** a dedicated patterns workspace with (1) containers named by
scientific field, (2) cross-field patterns in combination containers, (3)
"New pattern recognition in progress" bars with %, (4) potential-benefits display,
(5) a "New Patterns" left-sidebar menu item.

### Built
- **Page:** `templates/patterns_workspace.html` + route `/ui/patterns` (auth-guarded
  like the playground). Sidebar: "New Patterns" added to the playground menu and the
  workspace's own nav.
- **API (`app/pattern_api.py`, rebuilt cleanly):**
  - `GET /api/patterns/workspace` — patterns grouped into containers: single-field
    named by the field, >=2 fields become a combination container ("Field A + Field
    B", cross-field pill). Per-container: pattern count, library docs, analyzed docs,
    coverage %, live discovery job snapshots.
  - `GET /api/patterns/discovery-status` — library-wide: 5,398 docs, analyzed count,
    queued, candidate patterns, overall %.
  - `POST /api/patterns/discover/field/{field_slug}?max_documents=&max_chunks=` —
    background job (reuses load_progress engine) scanning a field's newest documents
    through the LLM extraction worker, then auto-generating benefits for new
    patterns. Global lock prevents concurrent discoveries (409 otherwise).
  - `GET /api/patterns/{id}/benefits` — LLM-generated 3 concrete benefit lines
    (Sentinel persona via gateway), cached in new `patterns.benefits` +
    `benefits_generated_at` columns (schema auto-migrated).
- **UI features:** per-container progress bar + % ("New pattern recognition in
  progress"), live polling (4 s) while a discovery runs, Start-recognition box
  (blank = scan all fields), pattern cards with status/type/confidence pills,
  Approve/Reject/Activate review buttons, benefits block (or "Analyze benefits"
  button).

### Verified live (scratch port 8077)
- Page 200; sidebar link present on the playground.
- Real discovery run on psychology (2 docs x 2 chunks): 3 NEW patterns proposed
  (ids 7-9), including cross-field "Encryption of Sensitive Behavioral Data"
  (psychology + computer_science) and a genuine cross_domain_bridge pattern
  (media_engineering + psychology). Workspace shows 7 containers.
- Benefits generated for pattern 9 in ~13 s: three concrete benefit lines (privacy
  compliance, protection of stigmatized data, safe ML integration). Cached.
- NOTE: gemma4:12B is CPU-bound on this laptop (~2 min per chunk; the trivial-call
  probe burned 19.5 s in thinking mode before the gateway's think:false path).
  Discovery is intentionally a background job with live progress; the new GPU
  machine will make this near-instant.

**Owner action:** restart run_smi.py + hard refresh; open /ui/patterns or click
"New Patterns" in the sidebar.

## §16 — Pattern reports (APA 7th), UI-only storage note, future-request foundations (2026-09-21, ~02:10 SAST)

**New module `app/pattern_report.py`** — report engine for the Patterns workspace:
- `build_report(container_key=...)` / `build_report(pattern_id=...)` collects patterns + evidence + library metadata.
- **APA 7th references**: author formatting (Surname, initials, & for multiple), year extraction, platform-aware source lines (GitHub `[Computer software]`, Hugging Face `[Data set]`), DOI/URL tails. File-path titles (data/knowledge_taxonomy/.../x.py) collapse to bare file names; slugged titles (DOC-1---...) are humanized. Fallback when the library row is gone: evidence row's document_title/source_url.
- **HTML renderer** (Georgia serif, APA hanging-indent works cited) and **PDF renderer** via the bundled `text_pdf.build_pdf_bytes` (pypdf — no new deps). Filename: slug of the container title + .pdf.
- Report covers **all container fields** (title = Field A + Field B; fields line), **data sources involved** (GROUP BY source_type/module/topic from library, top 40 with doc counts), and **Works Cited** (deduped across all patterns in the container).

**Endpoints (`app/pattern_api.py`)**:
- `GET /api/patterns/reports/container/{key:path}/report?format=html|pdf`
- `GET /api/patterns/reports/pattern/{id}/report?format=html|pdf` (renders the pattern's container report)

**Future-request foundations (user requests 6 & 8 — logged, not yet implemented)**:
- New table `future_requests` in patterns.db (kind, pattern_id, topic, fields, note, status, timestamps) + `record_future_request`/`list_future_requests` in pattern_store.py.
- `POST /api/patterns/future-requests/rd-paper` — "Request R&D Paper" launcher button on every pattern card (kind=rd_paper; auto-fills topic/fields from the pattern).
- `POST /api/patterns/future-requests/manual-discovery` — **User-Requested Pattern Discovery** card (kind=manual_discovery), clearly differentiated from the Automated card (mode pills on both).
- Route-order lesson: `GET /future-requests` must sit ABOVE `GET /{pattern_id}` or FastAPI matches the parametrized route first (500 int_parsing).

**UI (templates/patterns_workspace.html)**:
- Per container: "View Report (HTML)" + "Report PDF" buttons; **UI-only** purple "Archive" storage note (patterns.db / patterns / pattern_evidence / pattern_entities / pattern_relations / fields_involved) — verified ZERO storage references inside HTML/PDF artifacts.
- Per pattern: report buttons + "Request R&D Paper" (button flips to "R&D paper ✓ logged").
- Future-requests list renders under the manual-discovery card (top 6, kind-labeled).

**Verified live** (scratch port 8077): container HTML report 200; container PDF 200 (application/pdf, %PDF header, pypdf text-extraction confirms WORKS CITED / Wepener, P. / DATA SOURCES / PATTERNS / APA 7th all present); pattern PDF 200; R&D-paper + manual-discovery requests logged and listed (ids 1–2); page renders all new controls. Works-cited sample: `Wepener, P. (2026). Doc 1 Inpirari Drafting The Constitution Version 1. SMi Sentinel Domains.`

**Owner decisions logged**: R&D-paper template question answered (Sentinel learns the template from loaded candidate datasets — no owner-authored template needed; papers will be citation-grade like the reports). Interactive chat for manual discovery = future request, foundations laid via future_requests.

## §17 — App structure map + git audit + fresh SMI_Core repo (2026-09-21, ~03:55 SAST)

### The App's structure (reference for every future session)

**SMI_Core = Sentinel (this app). UI at http://127.0.0.1:8099/ui/playground. Run: `run_smi.py serve`.**

```
SMI_Core/
├── run_smi.py               entrypoint (serve --port 8099; scratch tests: --port 8077)
├── requirements.txt         no new deps needed for reports (pypdf bundled)
├── CONTINUITY_LOG.md        this log — read first
├── CREDITS.md               Buffy/Codebuff contribution credit
├── VALIDATION_PROTOCOL.md   external validation workflow
├── app/                     FastAPI application (2.3 MB)
│   ├── main.py              app factory, UI routes (/ui/playground, /ui/patterns, ...)
│   ├── config.py            settings loader (config/settings.yaml)
│   ├── db.py                dual SQLite: main DB (smi_vocationalllm.db) + library DB (library_gemma.db:
│   │                        documents, chunks, embeddings, ingest_events, unsupervised_runs)
│   ├── playground.py        Dashboard Home backend
│   ├── skill_review.py      Dataset Sourcing & Discovery: /find (GitHub+HuggingFace+OpenAlex in
│   │                        parallel, field-name-as-query), candidates CRUD, approve/reject/test,
│   │                        /candidates/{id}/ingest (background job), /progress/{job_id}, clear,
│   │                        identity_key dedupe (DOI/W-id, owner/repo, HF id) + partial UNIQUE index
│   ├── ingestion.py         digest+embed pipeline; ingestion mutex (serializes writers); 30s busy timeout
│   ├── load_progress.py     thread-bound progress engine (download 2-50 / digest 50-78 / embed 78-98 / done)
│   ├── sentinel_domains.py  per-field worker boxes: GitHub/HF fetch + store candidates
│   ├── openalex_worker.py   OpenAlex search + PDF/landing-page download lane
│   ├── pattern_store.py     patterns.db: patterns, pattern_evidence (document_id/chunk provenance),
│   │                        pattern_entities, pattern_relations, pattern_templates, future_requests
│   ├── pattern_worker.py    LLM extraction (entities/relations/patterns), cross-domain synthesis
│   ├── pattern_api.py       /api/patterns/*: workspace, discovery jobs, review, benefits,
│   │                        reports (container/pattern x html/pdf), future-requests (rd-paper, manual-discovery)
│   ├── pattern_report.py    APA 7th citation builder + HTML/PDF renderers (UI-only storage note stays out)
│   ├── llm_gateway.py       provider-agnostic gateway (Ollama today; Gemini-ready) — the "umbilical cord" to cut
│   ├── llm_firewall.py / gateway_guardian.py / sentinel_firewall.py / shell_policy.py / security.py
│   │                        the firewall stack (verified: llm_firewall_ok true)
│   ├── retrieval.py / chunking.py / parsing.py / library_router.py   RAG plumbing
│   ├── scientific_fields/   per-field configs (Biology, Chemistry_Material, Computer_Science_AI,
│   │                        Earth_Climate Sciences, Medicine_Health, Physics_Astronomy, deepmind_research)
│   ├── rag/ (indexer.py), apis/ (open-alex-api.md), deepmind/ (empty)
│   └── [legacy/aux modules: qualia, personal_growth, ayscio_pipeline, SMI_tunnel, ...]
├── templates/               12 UI consoles; key ones: playground_console.html (main dashboard),
│                            patterns_workspace.html (New Patterns), admin_console.html
├── config/settings.yaml + sentinel_policy.yaml
├── sentinel/                guardian/benchmarks/domains test harness (test_sentinel.py)
├── scripts/                 (empty)
├── data/                    6.7 GB runtime data — NOT in git: knowledge_taxonomy/, backups/, archives,
│                            gemma DBs, gemma_training/ (nomic-embed-text vectors)
├── VocationalLLM/           physically here but a SEPARATE app (ETDP) — excluded from this repo
├── [root test/tool scripts: adversarial_battery.py, make_test_pdf.py, run_locked*.py, ...]
```

**Three apps on this machine** (keep lean; no cross-references): ① Sentinel = SMI_Core (this repo),
② ETDP = VocationalLLM + its own repo + ETDP GitHub remote, ③ llama.cpp vendored clone (tooling, not ours).

### Git audit — findings (user asked: multiple gits, suspected corruption, fresh start?)

| Repo | Location | fsck | Verdict |
|---|---|---|---|
| ETDP repo | `/d/inpirari/.git` (wraps the WHOLE workspace!) | not fully run (too large) but HEAD/refs/status all healthy | miswired, NOT corrupted |
| ETDP repo (2) | `SMI_Core/VocationalLLM/ETDP/.git` | clean; HEAD = 74f5e32 | healthy |
| llama.cpp | `Ollama/llama.cpp/.git` | clean; HEAD = 56381e40 | healthy |
| **Sentinel (new)** | `SMI_Core/.git` → branch `main`, commit bb3eeb6 | **clean (exit 0)** | **fresh start created** |

- **No corruption found anywhere.** The confusion: the ETDP GitHub repo (`origin → https://github.com/ETDAI/ETDP.git`,
  branch `etd.github.io`) is checked out at `/d/inpirari` ROOT, so every Sentinel file shows as untracked/modified ETDP content.
- The outer repo holds **nothing unique** (0 commits ahead of origin) and ~100 files differ only as an ETDP checkout.
- 3 IDE worktree branches hang off the outer repo: fading_ray_fires_06h02, fiery_drift_rolls_15h59 (Gemini), and
  **liamdecker68-sudo-light-ide-chat-imports = 20 commits NOT on origin — PRESERVED, do not delete** (owner to review).
- **Action taken (additive only):** created fresh repo inside SMI_Core — branch `main`, single commit bb3eeb6,
  102 files (code+docs), `.gitignore` excludes data/ (6.7 GB), Logs/, uploads, venv, secrets (1-run-key.txt), .freebuff/, VocationalLLM/.
- **Nothing was deleted.** ETDP checkout at root untouched; untangling `/d/inpirari/.git` is the owner's call (needs the
  IDE worktree branches resolved first): plan = clone ETDP fresh elsewhere → archive worktrees → remove root `.git` → ETDP apps live in their own dirs.

### Future request (logged by owner): restructure SMI_Core to GitHub-standard layout
Decided: **future request, not now** (code churn on the eve of the machine migration). When done: `src/sentinel_core/`
package layout, tests/ dir, pyproject.toml, docs/, CI (ruff+mypy+pytest), pre-commit, pre-release data-path audit
(every `data/...` reference must point at a configurable root before any repo move). Tracked in this log; do NOT
lose sight of it on the new machine.

### §17 addendum — Sentinel repo safety sweep + baseline tag (2026-09-21, ~04:20 SAST)
Owner asked to "start with the commit to ensure we are safe" for Sentinel.git containing ONLY the Sentinel app. Verified:
- **Scope**: 102 tracked files = Sentinel code + docs only. Index audit: 0 files under data/, VocationalLLM/, .freebuff/, Logs/; no 1-run-key.txt, no .env, no *.key, no ingest_status.json.
- **Secrets**: git grep for real credential formats (Google AIza…, OpenAI sk-…, AWS AKIA…, GitHub ghp_…, Slack xox…, PEM private keys, `api_key/password/secret/token: <16+ char value>`) → **zero hits**. Generic "key/token" matches are code identifiers only.
- **Integrity**: git fsck exit 0; working tree clean (0 uncommitted).
- **Safety point**: annotated tag `v0.1.0-lean-baseline` on 5b6085f — any future experiment can be measured/reset against it (`git describe`, `git diff v0.1.0-lean-baseline`).
Rule going forward: every commit in this repo must keep the app lean — if a change wants to track data/, models, or ETDP, stop and reconsider.

## §18 — Fourth sourcing lane: PubMed/PMC for the medical fields (2026-09-21, ~05:30 SAST)

Owner added `pubmedapi.md` (NCBI API key — 36 hex chars, VERIFIED WORKING) and `pubmedprocess.md` (E-utilities
two-step process guide) in SMI_Core root. Built the lane per that guide:

**New `app/pubmed_worker.py`**:
- **Field gate** `pubmed_field_allowed()`: PubMed participates ONLY for Health, Medicine, Psychology, Neuroscience
  (+ compound variants: "Medicine & Health", "Public Health", "Pharmacology", "Neuroscience & Psychology",
  "Genetics & Molecular Biology"). Physics/Engineering/Economics etc. are blocked.
- **Search** (`search_pubmed_papers`): esearch (term + optional year filter) -> PMIDs -> esummary JSON (title,
  journal, date, authors, DOI, PMCID via articleids). Rate-limited thread-safely: 0.11 s keyed / 0.35 s keyless.
- **Load** (`load_pubmed_papers_into_field`): attempt 1 = PMC Open Access FULL TEXT via efetch db=pmc (XML ->
  plain text, stored under `data/knowledge_taxonomy/scientific_fields/<field>/pubmed/`); attempt 2 = PubMed
  abstract (always available). Then `ingest_files` digest+embed with progress — same pipeline as all lanes.
- API key read order: `NCBI_API_KEY` env -> `pubmedapi.md` (only if it matches the 36-hex key format).

**Wiring in `skill_review.py`**:
- `/find` now runs **four sources in parallel** (ThreadPoolExecutor max_workers=4); response adds `pubmed_count`.
- **Identity**: PubMed candidates resolve to `doi:<doi>` FIRST (same DOI as OpenAlex = same paper, ONE row),
  else `pmid:<id>`, else `pmc:<id>`. Legacy pmid:* identities are auto-upgraded in `_ensure_schema` (reads both
  top-level and legacy nested `_metadata` shapes).
- **Load dispatch**: `source_type == "pubmed"` -> `load_pubmed_papers_into_field` with pmid/pmcid from metadata
  (endpoint reads both metadata shapes for legacy rows).
- Re-matched candidates now refresh `metadata_json` too (was description/field/license only).

**UI**: all sourcing labels/status lines mention PubMed; hint notes the medical-fields-only gate; per-field
labels updated ("GitHub + Hugging Face + OpenAlex + PubMed searched together").

**Verified live (port 8077)**:
- Gate exact: Medicine/Psychology/Neuroscience/Public Health ALLOWED; Physics/Engineering/Economics blocked.
- Medicine search "long covid fatigue": 6 PubMed candidates (2 PMC open-access) among 18 total from 4 lanes.
- **Full cycle**: approve -> Load candidate 264 -> **PMC full text 159,758 chars downloaded + ingested as
  document 5405**, candidate status `loaded`, linked. (A first test stored the abstract fallback — legacy
  metadata shape — then re-load with PMC text; abstract doc 5404 removed to avoid duplication.)
- Psychology search "mindfulness anxiety": 3 papers (abstract-only records) — gate + search OK.

**Key security**: `pubmedapi.md` (the real key) is gitignored — a credential must never enter the repo.
`pubmedprocess.md` also kept local (contains pasted third-party chat content); the design lives in the
worker's docstring. Files remain on disk for migration.

### §18 addendum — PMC availability badges + open-access-first lineup (2026-09-21, ~06:15 SAST)
- **`pubmed_worker.py`**: candidates now carry top-level `pmid`/`pmcid`/`doi`/`has_full_text` (no more nested-only
  `_metadata`); search fetches a 3x-wider PMID pool and **stable-sorts PMC full-text papers to the top** of the
  lineup (NCBI relevance order preserved within each group) before trimming to the limit; response adds
  `full_text_count` (in lineup) + `full_text_available` (in pool).
- **`skill_review.py`**: `/find` response adds `pubmed_fulltext_count`; `/candidates` listing surfaces
  pmid/pmcid/doi + `has_full_text` for stored PubMed rows (both metadata shapes) so the panel pills work
  everywhere; transient `journal` NameError from the refactor caught and fixed by live test.
- **UI**: green **"PMC full text ✓"** pill vs amber **"Abstract only"** pill on every PubMed card (both the
  global review panel and per-field sourcing); status line reports "with N full text".
- **Verified live**: Medicine search → lineup order FULL×6 (9 full-text in pool); stored-rows enrichment
  8/8 has_full_text, 5/8 pmcid; UI strings present. One restart + hard refresh picks it up.

### §18 addendum 2 — "PubMed full text only" toggle (2026-09-21, ~07:00 SAST)
- **`pubmed_worker.search_pubmed_papers(full_text_only=)`**: adds `AND free full text[sb]` to the esearch term
  (EMPIRICALLY VERIFIED: `open access[filter]` and `pmc open access[filter]` return 0 hits; `free full text[sb]`
  returns ~144k) + defense-in-depth post-filter dropping any record without a PMCID.
- **`FindRequest.pubmed_full_text_only`** threaded through `/find`.
- **UI**: checkbox "PubMed full text only (skip abstract-only papers)" in the global panel; "Full text only"
  checkbox in every field's sourcing row. When ON, results views hide abstract-only stragglers too
  (`hideAbstractOnly`, applies to panel listing incl. stored rows) and status notes "· full text only".
- **Verified live**: OFF → PMC papers lead (mixed lineup, PMC-first); ON → 6/6 PubMed papers with PMCIDs.
  One restart + hard refresh picks it up.

## §19 — Philosophy field + sourcing-label bump + future-sources policy (2026-09-21, ~07:40 SAST)

**Owner directive (recorded for all future sessions):** additional data sources WILL be added as the project
progresses; for now we concentrate on scholarly sources that "have done the hard work and include cited works"
(OpenAlex, PubMed/PMC). When evaluating new sources, prefer those with citation graphs and stable identifiers.

**(1) Philosophy as a Scientific Field** (owner: "the origin... starting point of all sciences"):
- Added to `SENTINEL_DOMAINS` in **Human Behavior and Society (Guardian of Minds & Cultures)** — FIRST position,
  beside Psychology, exactly as the owner requested ("same category as Psychology").
- detail: "ethics, epistemology, metaphysics, logic, philosophy of science" (drives OpenAlex concept matching).
- Also mapped into the **Neuroscience & Psychology** main-LLM room (SENTINEL_ROOMS).
- Architecture note: `_resolve_field` auto-derives slugs/dirs/status from the domain list — NO rewrites needed
  anywhere; the field gets worker boxes, sourcing, capacity bar, uploads, ingestion, reports for free.
- Sources: all three GitHub/HF/OpenAlex lanes remain active per owner instruction ("one might never know what
  they produce"); **PubMed is excluded automatically** by its medical-fields gate (verified: pubmed_count=0).
- **Verified live**: status lists Philosophy first in the domain; search "Philosophy" returned 15 candidates —
  5 OpenAlex (incl. Anscombe's "Modern Moral Philosophy", "Philosophy in the Flesh"), 5 GitHub, 5 HF.

**(2) Ribbon label size**: `.sentinel-ribbon .rname` (the vertical field names in the library-share bar under the
Sentinel Pie Diagram area) bumped **9.5px → 11px** (+1.5pt), orientation (vertical-rl) untouched.

Commit: philosophy field + label bump. One restart + hard refresh picks both up.

## §20 — Pattern recognition pause switch (owner request: OFF until the new rig) (2026-09-21, ~08:20 SAST)

Owner reported background resource use and asked for pattern recognition to be switched OFF until the machine
migration, while keeping candidate sourcing/uploads fully working. Delighted the workspace is an eye-opener! 🎉

**Diagnosis first**: there is NO always-on pattern thread. The resource consumers are (a) discovery jobs started
from the Patterns workspace (background LLM threads, minutes per document on this laptop) and (b) any NEW job
starts. Auto-ingest digesting files is separate and unaffected.

**Built — persisted master switch**:
- `pattern_settings` table in patterns.db + `get_pattern_recognition_enabled()` / `set_pattern_recognition_enabled()`
  (default ON; survives restarts).
- **Gates**: `discover/field/{slug}`, `analyze/{id}`, `process-queue`, `synthesize` all refuse with 409 +
  PAUSED_MESSAGE while paused. `extract_document` checks the switch at every CHUNK boundary — a running job
  stops mid-document at the next chunk (no wasted LLM cycles).
- **Cancellation**: `load_progress.cancel_job(job_id)` + `is_cancel_requested()`; pausing cancels all
  `_ACTIVE_DISCOVERY` jobs; the discovery loop exits cleanly at the next document boundary with
  `{"cancelled": true, "analyzed": N}`. `ProgressReporter` now exposes `.job_id`.
- **API**: `GET/POST /api/patterns/recognition-switch` — NOTE: defined ABOVE `GET /{pattern_id}` (the §16
  route-order lesson struck again on the first attempt).
- **UI**: "Pattern recognition ON/PAUSED" checkbox in the Library-wide recognition card; red paused banner;
  status line shows the state; discovery start button surfaces the paused message if clicked.

**State now: OFF (as requested).** Verified live: GET shows `recognition_enabled:false`; discovery refused 409;
resume/re-pause cycle persists; sourcing while paused returned 9 Philosophy candidates — uploads/loads unaffected.
On the new rig: flip the toggle in the Patterns workspace (or POST recognition-switch {"enabled":true}).

Commit: pause switch. Restart + hard refresh to see the toggle.

---

## §21 — Priority fixes: slow scholarly loads, reject flow, English-only, accordion (2026-09-21)

Owner reported five issues (priority order). All fixed and verified live on :8077:

1. **OpenAlex/PubMed slow + "server error" on Load** — root causes found and fixed:
   - `_retry_get()` in `openalex_worker.py`: every GET (search, work record, PDF/landing-page download) now retries 3-4x with exponential backoff (1.5/3/6s) on 403/408/429/5xx and connection drops. PubMed's `_eget()` reuses it. Any single network hiccup no longer kills a load.
   - PubMed esummary split into batches of 40 pmids (wide pools previously over-ran one request's budget → whole-lane failure).
   - `/find` deadline raised to 75s; GitHub/HF timeouts trimmed 30s→25s; **pool.shutdown(wait=False, cancel_futures=True)** so a crawling lane can never block the search response (a `with ThreadPoolExecutor` join secretly did exactly that).
   - Verified: searches 2-3s across all four lanes; OpenAlex load → full HTML in 4s; PubMed load → complete 138KB PMC paper, 145 chunks embedded, per-chunk progress in 7s.
2. **No issues with GitHub/HF** — untouched.
3. **Rejected datasets vanish immediately** — `review_candidate(reject)` now DELETES the row (no status='reject' residue; legacy reject rows also filtered from every view) and records the identity in `patterns.db → rejected_identities` (new table, functions `remember_rejected_identity / rejected_identities / forget_rejected_identity`). UI fades the card out (~0.25s) and splices it from the in-memory lineup; status line explains the removal.
4. **English-only intake (owner directive, coded as OA_ENGLISH_ONLY / PM_ENGLISH_ONLY flags)** — OpenAlex: server-side `language:en` filter + per-work safety net (`_is_english_work`, language field added to the select). PubMed: `english[lang]` in the term + [lang]-title-tag heuristic (title-endswith tags like `[french]`). GitHub/HF already English-first (left untouched).
5. **Rejected datasets never reappear** — two layers: the persisted `rejected_identities` cache (survives restarts, independent of Clear) enforced during in-batch dedupe (identities exist there) + the DB legacy-reject check at storage time. Verified end-to-end: rejected → re-search → absent (dups counter increments).
6. **Field containers collapse on click (mouse-hold workaround)** — the grid click handler collapsed an expanded container on ANY non-button click, including the search input. Now an expanded container collapses ONLY on its header row (`.sentinel-field-row`); clicks in inputs/results/sourcing area never close it. Collapsed rows still open on any click.

**Bonus bug found by live testing:** fresh `/find` inserts never received their DB id (`item["id"] = cur.lastrowid` was missing) — Approve/Reject/Load buttons on brand-new results would have 404'd. Fixed.

Known quirk (pre-existing, not from §21): a server killed mid-boot on this laptop can leave a wedged socket that accepts but never answers — external tool timeouts (e.g. curl exit 28) may mask a healthy app. Always verify `curl /ui/playground` after a forced restart.

---

## §22 — OpenAlex as primary R&D source; PDF quality layer; review-while-loading safety (2026-09-21)

**Owner's directives this session:** OpenAlex is the primary R&D source (owner calls it a "treasure trove" — cited, moderated, high-standard works); focus on enhancing its methods/process; investigate download formats (.csv/.xml vs .pdf); port the ETDP three-layer PDF sanitizer quality; prioritize candidate lineups 2020→current, most-cited top-down.

### Concurrency question answered (owner reviews/rejects while a Load runs)
SAFE by design — verified against the code:
- Loads run in their own background thread and only touch the gemma library DB, guarded by `_INGEST_WRITE_LOCK` + a 30s busy timeout (`ingestion.py`). Review actions only touch `skill_review_candidates` (different DB) — no shared write path.
- Reject during a load deletes only the candidates row; the running load is unaffected, and its finalize UPDATE (by candidate id) matches zero rows harmlessly. The one nuance: rejecting the dataset *currently loading* does not abort that download (it already started) — by design.
- Owner's one-at-a-time loading discipline is ideal on this laptop; approving/rejecting/test-listing concurrently has no effect on load progress or ingestion.

### What was built
1. **Lineup priority (owner directive):** `search_openalex_works` now defaults to `from_publication_date:2020-01-01` (pass `from_year` to widen) and stable-sorts candidates most-cited first (relevance order preserved within equal citations). Verified live: `6342 → 5258 → 3509 → 2696 → 2053 → 1758 → 1144 → 909 → 646`, all 2020+.
2. **PDF quality layer:** SMI's `parsing.py` already carried the full layered stack from the ETDP era (poppler → Dangerzone → docling → Stirling → OCR + noise stripping) — dormant because config never enabled it. Now ACTIVE via `settings.yaml → pdf_preprocess: engine=pipeline`:
   - Primary: **poppler/pdftotext** (found on this machine via Git's bundled tools), `-layout` mode.
   - Deeper layers (Dangerzone sanitize, docling AI extraction, Stirling, EasyOCR) auto-engage **as soon as they're installed** — no code changes needed; they are also available on the new rig by installing them.
   - New `_polish_pdf_text()` quality pass on ALL pdf text: de-hyphenation across line breaks, soft-wrap joins (paragraph breaks preserved), whitespace collapse, page-artifact line removal. Verified on a real 73K-char PDF (engine label `poppler`).
3. **Download formats — investigated, decision recorded:** OpenAlex/PMC scholarly download reality: PDFs where publishers provide them, HTML full text otherwise (already Sentinel's preference — cleaner text, no PDF parsing), metadata JSON as final fallback. CSV is only offered for OpenAlex's *bulk dataset exports* (full-database snapshots, GBs — a bulk-loading lane for the new rig, NOT per-paper downloads); XML is PubMed's internal format already handled by `_pmc_full_text`. Conclusion: keep the current PDF→HTML→JSON cascade; it already chooses the cleanest available format per work.
4. **UI:** hints on both panels now state "OpenAlex is the primary R&D source — 2020–current, most-cited first".

---

## §23 — THE OLLAMA CORD-CUT: fully staged, one-flag flip (2026-09-21)

**Owner directive (recorded as policy): the Ollama cord must be cut ASAP, completely.**

### Audit findings
- `llm_gateway.py` (built earlier) already had ollama/gemini/openai_compatible providers with fallbacks — but only pattern extraction used it. Chat + ALL embeddings still flowed through the direct `OllamaClient` (ingestion, conversation, playground, session_memory, main).
- Firewall paradox: `enforce_ollama_provider: true` + default blocked substrings `["gemini","google","palm"]` actively FORBADE the destination we're moving to.
- Live Gemini verification against the owner's AQ…-format key surfaced three era-shifts: (1) the legacy `?key=` auth 503s — header auth (`x-goog-api-key`) is now canonical; (2) all dated models are RETIRED (gemini-2.0/2.5-flash 404) — rolling aliases (`gemini-flash-latest`, `gemini-flash-lite-latest`) are the durable names, and lite aliases reject `thinkingConfig` (400 → adaptive retry added); (3) `text-embedding-004` is gone → `gemini-embedding-001`, which accepts `outputDimensionality: 768` (Matryoshka truncation) — EXACTLY the library's nomic-embed vector schema.
- Library reality: 186,744 chunks, of which **152,839 have NO embedding** (CPU-era gap) — the migration is both a re-space and a completion.

### What was built
1. **Gateway hardening**: header auth, chat fallback aliases per-provider, adaptive thinkingConfig retry, `gemini-embedding-001 @ 768 dims` (verified live: chat 'CORD CUT OK', embed 768).
2. **`GatewayBackedClient`** — drop-in replacement for OllamaClient (chat/embed/is_available/list_models/get_runtime_diagnostics), so ALL modules move providers with zero call-site changes.
3. **The switch**: `runtime_llm.client_backend: ollama_client | gateway` read by `build_ollama_client()` (name kept for import stability); main.py's two direct constructions now route through it.
4. **Firewall modernized**: new `allowed_runtime_providers: [ollama, gemini]` (gemini pre-authorized so the flip needs no firewall edit); legacy enforce-flag defers to the allow-list; Ollama model policing (blocked substrings, SMI4 allow-lists) now applies only when provider == ollama.
5. **`scripts/reembed_gemini.py`** — resumable (reembed_done table), dry-run-by-default migration: scopes old/missing/all, probes 768-dims before writing a single row, batched commits + ETA. Verified dry-run: 186,760 candidates found, zero writes.

### THE FLIP (new rig, ~5 minutes)
1. `config/settings.yaml`: `llm.provider: gemini` + `runtime_llm.client_backend: gateway`
2. `.env` carries GEMINI_API_KEY (already verified live)
3. Restart → every chat and every NEW embedding flows Gemini (no Ollama needed, at all)
4. `python scripts/reembed_gemini.py --scope all --apply` (budget ~9-17h one-time; resume anytime)
5. Optional decommission afterwards: stop relying on Ollama entirely — the app no longer references it for any LLM traffic.

Current state on THIS laptop: UNCHANGED (staged, verified both firewall states PASS, server boots, status endpoint green).

---

## §24 — Load reliability: the post-load freeze killed; Search Library workspace (2026-09-22)

Owner reports: loads freeze the app until reboot; OpenAlex/PubMed downloads crawl and die after ~10 min;
non-English still leaking through; failed loads leaving debris. Diagnosed and fixed:

### The freeze — root cause chain (proven)
1. A Load succeeds → paper lands under `data/knowledge_taxonomy/scientific_fields/<field>/...`.
2. **Auto-ingest daemon** (10s poll; default roots = raw_root + **taxonomy_root**) re-discovers the
   file ~10s later and re-digests it with `allow_embeddings=False` → same checksum →
   `reset_document_chunks` **deletes the freshly embedded chunks** and re-inserts them with NULL vectors.
3. Each embed call on this laptop can hang ~20s; ×145 chunks ≈ 48 min of crawl **while the global
   ingest write-lock is held** → every other writer (loads, uploads, chat) starves → "frozen, must reboot".
**Fixes:** auto-ingest never scans `scientific_fields` (root-name + per-path parts guard);
verified live: scan returns 0 field files (17 legacy strays remain, matching the 17 unembedded
"Other fields" docs — victims of the old behavior).

### Hard budgets (owner: "no download may run 10 minutes")
- OpenAlex/PubMed load chains enforce a **150s wall-clock deadline** (stream-body + element-loop checks).
- Per-document **embed budget** `ingestion.embed_budget_seconds: 300` (settings.yaml): chunks that miss
  the budget store without vectors (re-embed migration can fill them); 3 consecutive embed failures
  → continue without vectors instead of stalling. Latency probe during a real load: worst 0.24s.

### English-only enforced at every layer (owner directive)
- OpenAlex: `language:en` server-side + per-result filter + **metadata-record re-check before digest**
  (non-English record files deleted on arrival).
- PubMed: `english[lang]` + metadata filter.
- **New last-line ingestion gate** (`enforce_english: true` on scholarly loads): codepoint-range
  heuristic (Latin-ext/Greek/Cyrillic/CJK/Arabic...) rejects dense non-English bodies at digest time.

### Failed load = clean field + permanent reject (owner directive)
- `_ingest_candidate_impl`: on failure → `purge_field_documents(field, attempted_doc_ids)` (new helper,
  sentinel_domains.py) removes any partial documents/chunks/FTS rows; artifact files unlinked;
  identity → `remember_rejected_identity` so the dataset **never reappears**.
- Workers also unlink artifacts when a digest ingests 0 files. Reject now also blocks **same-title
  variants** (same work under a different URL can no longer dodge the cache).

### NEW: Search Library workspace (`/ui/search`, templates/search_workspace.html, app/search_api.py)
- Library as a **searchable database** grouped under the five main scientific areas (Sentinel domains);
  opening a domain reveals field containers; opening a field lists its datasets (title, source,
  authors, date, chunk count, "Searchable / Vectors pending" badge).
- Per-container search box (title/author/source, library-wide `?q=` also works); Preview (HTML modal,
  chunk view) and Download .pdf buttons per dataset. Endpoints: `/api/search-library/overview`,
  `/api/search-library/documents`. "Other Recorded Fields" catch-all keeps nothing hidden (17 legacy
  docs surfaced).
- **Playground lightened (owner directive):** per-field loaded lists replaced by a count + link to the
  Search Library; sidebar gains "Search Library".

### Live proof
- OpenAlex load "Review of Particle Physics": ok, 215 chunks / 195 embedded, 23.2s total, app stayed
  responsive (12 probes, worst 0.24s). Document immediately visible in Search Library.
- Reject cycle: TURBOMOLE paper rejected → re-search → does NOT reappear.
- Overview: 5,555 datasets / 184,363 chunks across 5 domains + Other.

One action: restart `run_smi.py` + hard refresh. §23's staged Gemini flip remains ready.

---

## §25 — Sequential load queue (owner directive, 2026-09-22)

"Add a background queue so multiple candidate loads can be lined up and processed one at a
time automatically, with per-job status in the UI."

### app/load_queue.py — the queue
- **Single worker thread** ⇒ two loads can never overlap (the §24 freeze can not recur).
- Each entry pre-creates its live progress job at enqueue time (queued → running), so UI cards
  show "Queued — position N" instantly and keep polling the same job once running.
- `_MAX_QUEUE = 25` waiting; finished entries trimmed to 60. Duplicate enqueue of the same
  candidate returns the existing entry (`already_queued: true`) instead of double-loading.
- Cancel: queued entries stop instantly (job closed); a running load is stopped cooperatively
  at the next chunk/download boundary.
- **Recovery on failure**: an errored load goes through §24's purge + permanent-reject path
  unchanged (the queue calls the same `_ingest_candidate_impl`), so a failed queue entry leaves
  the field clean and the dataset never returns.

### Cooperative cancellation plumbing
- `load_progress.LoadCancelled(BaseException)` — deliberately BaseException so the lanes'
  broad `except Exception` blocks cannot swallow a cancel.
- `load_progress.cancel_requested()` — true when the job bound to the current thread was asked
  to cancel; checked in the ingest embed loop (chunk boundary), the ingest file loop, and both
  workers' download loops.
- `load_progress.start_job(..., initial_state=, initial_message=)` for pre-created queued jobs;
  `mark_job_running()` flips state when the worker picks an entry up.

### API (skill_review router)
- `POST /api/skill-review/candidates/{id}/ingest` now **enqueues** (returns entry_id + position;
  409 when the queue is full). `?wait=1` unchanged for tooling.
- `GET  /api/skill-review/load-queue` — full snapshot with live progress per entry.
- `POST /api/skill-review/load-queue/{entry_id}/cancel` — queued instant / running cooperative.

### UI (playground_console.html)
- **Load queue panel** under the Discovery & Review lineup: per-job title, field, source,
  state pill (Queued #N / Running / Loaded ✓ / Failed / Cancelled), live % bar, Cancel button.
  Shows itself while jobs are active or recently finished; parks its 3s poller when idle.
- The Load flow on every card now tracks its **queue entry** (not just one job): shows
  "Queued — position N" while waiting, then live download/digest/embed %, then done — and
  multiple queued cards all keep updating from the same snapshot.

### Live proof (port 8077)
- Queue q1+q2 (Astrophysics): progress trail `q1:download → q1:digest → q2:download → ...`,
  **zero concurrency violations**, both papers ingested (1 doc each).
- Cancel of a running load: stopped "before the next download", final state `cancelled`,
  nothing ingested.

One action: restart `run_smi.py` + hard refresh (Ctrl+F5).

---

## §26 — Re-embed migration dry-run: backfill sized (2026-09-22)

Dry-run (`scripts/reembed_gemini.py`, zero writes) + victim breakdown + measured rate:

### The backlog
- **scope=old**: 34,195 chunks carrying nomic vectors (was 33,905 at §23 — +290 from new loads).
  These MUST migrate at flip time; mixed vector spaces poison retrieval.
- **scope=missing**: 153,660 chunks with no vector at all (was 152,839 — +821 net).
- **scope=all**: **187,855 chunks** = the complete one-time migration.

### Where the gaps live (the owner's question)
- 108,006 chunks **outside** the field containers (legacy/curriculum-era uploads, raw roots)
  — the CPU-era gap: never embedded at all.
- 45,654 chunks **inside** field containers (GitHub/HF pulls + earlier uploads) — these are
  the auto-ingest-stripped victims (§24 root cause; the guard now prevents new ones).
- **0** in the openalex/pubmed containers specifically — every scholarly paper loaded through
  the load lanes carries vectors.
- Document view: **3,740 of 5,588 documents (67%) show "Vectors pending"** — two-thirds of the
  library is only lexically searchable today. The backfill is the single biggest retrieval
  upgrade available.

### Measured rates (honest numbers)
- **Local nomic-embed measured at 16.97/s on this laptop** (10/10 sample, Ollama healthy):
  missing-only ≈ **2.5 h**; all ≈ **3.1 h** — far better than feared, WHEN Ollama is responsive.
- Gemini (gemini-embedding-001 @ 768, §23-verified): expected ~2.5-4/s ⇒ ~13-21 h for all;
  rough API cost order: ~$50-60 one-time at ~2k tokens/chunk (verify current pricing).

### Strategic note for the flip decision
Filling the 153,660 gaps **locally with nomic** is tempting (2.5 h, free) — but at the Gemini
flip those become *old*-scope vectors that must be re-done anyway (missing → old grows from
34,195 to 187,855). Recommendation stands: do **one** migration, on Gemini, on the new rig
(`--scope all --apply`), after throwing the two-line flip. Until then the app degrades
gracefully (lexical-only retrieval for null-vector chunks; §24 budgets keep loads healthy).

Resumability: `reembed_done` table records progress; any interrupted run continues where it
stopped. Dry-run remains the default; `--apply` required to write.

---

## §27 — Legacy un-embedded purge executed after review (2026-09-22)

Owner directive: "purge the 108k legacy chunks outside the field containers that were never
embedded and are not part of Sentinel's sciences — after listing them for review."

### The review changed the plan (this is why we list first)
The 108,006 outside-container never-embedded chunks are NOT all junk:
- **104,784 are `computer-and-information-sciences`** — the Qwen-era coding corpus
  (repo files + German FastAPI docs), sitting outside containers only because it predates
  the layout. A Sentinel science on paper → NOT auto-purged; owner decision pending
  (note: the German docs also violate the English-only directive).
- **3,220 belong to field-labeled documents** (incl. SENTINEL-v2, the Constitution, concept
  papers) → kept, untouched.
- **The true junk: 2,922 chunks / 28 blank-field documents** — duplicate uploads
  (Quantum_Doctrine ×5, Organisation_Design ×8, qualia-lab ×2, all content preserved in
  archived originals or better-labeled siblings) + stale `instructions_*` session notes.

### Executed
`scripts/purge_legacy_unembedded.py` (dry-run default, `--apply` executed):
- gzip backup first: `data/exports/purge-backup-legacy-unembedded.json.gz` (830 KB, every
  document row + full chunk text) + manifest in `Logs/`.
- **Resurrection guard**: `file_ingest_state` 'ok' rows (main DB) for all 16 unique source
  paths, so auto-ingest cannot re-digest the purged files.
- Atomic delete of chunks + chunk_fts + documents.

### Verified after purge
- 0 doomed docs/chunks remain; documents 5,588 → **5,560**; chunks 187,855 → **184,933**;
  never-embedded backlog 153,660 → **150,738** (re-embed dry-run numbers shift accordingly:
  scope=all ≈ 184,933).
- Owner's papers intact (SENTINEL-v2 ×2, Constitution ×2, Quantum_Doctrine #3 under
  "Quantum Physics"); all field containers intact (CS&AI 105,104 chunks; Biology,
  chemistry, Psychology, Physics, materials-science …).
- Two script bugs caught live (guard table lives in the main DB; sys.path for app imports)
  — fixed before any deletion occurred; the transaction had aborted cleanly both times.

### Open decision for the owner
The Qwen-era coding corpus (104,784 CS&AI chunks outside containers, largely German + code):
keep (it is a Sentinel science and may feed future CS fine-tuning), purge as Qwen traces per
the lean-Sentinel directive, or migrate it into the CS&AI container properly. A separate
review listing can be produced anytime.

## §28 — Word Add-in persistent sideload (ETDP APA 7 Research Assistant) — 2026-09-22, ~04:15 SAST

**Problem:** Owner's Word citation add-in (`manifest.xml` + `server.js` + `web/`) vanished from Word after every Office update. Prior attempts used `office-addin-dev-settings register` / `npm run sideload` (session-scoped developer registrations that Word tooling removes) and Word-on-the-web upload (per-session).

**Root cause identified:** No Trusted Catalog existed (`HKCU\...\WEF\TrustedCatalogs` was empty). Dev-style sideloads are ephemeral by design; the persistent mechanism is a Trust Center **trusted folder catalog**, which Word re-enumerates at every startup and Office updates never remove.

**What was done:**
- Project copied from `C:\Users\m3isd\personal\ETDP\word-addin-apa-assistant` to **`D:\Word-add-in`** (owner's intended location — the LIVE copy; edits belong here now).
- Dev cert CA installed/trusted (`office-addin-dev-certs install`, user Root store).
- **Trusted Catalog registered** (HKCU, Flags=1): `HKCU\Software\Microsoft\Office\16.0\WEF\TrustedCatalogs\{E7A1F3C2-5B9D-4E6A-8F4C-1D2B3A4C5D6E}` → `D:\Word-add-in\`.
- Server hardened: `PORT=0` sandbox-env bug guarded (falls back to 3000); runs as `run-server.cmd` (hidden via `start-hidden.vbs`), logs to `server.log`; live on `https://localhost:3000` (127.0.0.1 + ::1).
- Logon autostart via HKCU Run key `ETDP-Word-APA-Server` (schtasks needed admin; Run key doesn't).
- **One-click repair tool:** `D:\Word-add-in\repair-word-apa-sideload.cmd` — re-trusts certs, re-registers catalog, re-arms autostart, restarts server. Run whenever the add-in ever disappears.
- Manifest passes official `office-addin-manifest validate`.

**Owner steps (once):** close ALL Word windows → reopen → Insert > My Add-ins > **SHARED FOLDER** tab → "ETDP APA 7 Research Assistant" → Add. Ribbon button lands in Home > "ETDP Research Tools".

**Word is left running untouched** (owner's documents open); catalog is read at Word start, hence the restart.

**§28 CORRECTION (same day, ~04:35):** Drive-letter catalog URLs (`D:\Word-add-in\`) are silently ignored by current Word builds — the trusted-folder catalog REQUIRES an SMB share and a UNC Url (`\localhost\WordAddin`), per MS docs "Sideload Office Add-ins on Windows from a network share" (learn.microsoft.com, 2026-06-11). Fixed: created SMB share `WordAddin` → `D:\Word-add-in` (elevated, owner-approved), rewrote catalog Url to `\localhost\WordAddin` + `Id` value (via Python winreg to avoid shell backslash mangling), repair script updated to match. Word cycled fresh after the change. Lesson: Word's Shared Folder enumeration wants UNC; HKCU reg writes through Git Bash need winreg/PowerShell-single-quoted to preserve double backslashes.

## §29 — Word Add-in: sideload WIN + OpenAI purged → Google Gemini — 2026-09-22, ~05:10 SAST

**The add-in now loads in Word.** Working mechanism (after the folder-catalog path was suppressed on this consumer build O365HomePremRetail 16.0.20326): the **developer sideload registration** (`HKCU\...\WEF\Developer\{add-in GUID}` → manifest path) via `office-addin-dev-settings register`. Owner confirmed the add-in appears and opens.

**Self-healing against Office updates (the original complaint):** `D:\Word-add-in\rearm-sideload.ps1` runs at every logon (via `start-hidden.vbs` → HKCU Run key `ETDP-Word-APA-Server`): re-writes the dev-sideload key, re-ensures the trusted-catalog entry, and starts the HTTPS server if down. After any Office update clears the registration, the next logon restores it before Word launches. `repair-word-apa-sideload.cmd` = manual one-click version. Logs to `rearm.log`.

**OpenAI → Google Gemini (owner directive, portfolio consistency):**
- `taskpane.html/js`: provider dropdown OpenAI→Google Gemini (recommended), model default `gemini-flash-latest`, key field; all OpenAI fetch/localStorage/UI refs replaced.
- Gemini call uses **header auth** (`x-goog-api-key` — §23 lesson: `?key=` is deprecated) against `generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`; manifest AppDomain updated.
- Key auto-fill: server endpoint `/api/local-config` reads the Gemini key from `D:\inpirari\.env` (parent dir — NOT SMI_Core) and the task pane pre-fills it at load (loopback-only; key never stored in the shared folder).
- Source discovery remains **Crossref** (cited-works quality, per owner's source policy).

**Owner next actions:** restart Word / reopen the task pane to load the new HTML+JS (Office caches the pane); select Paraphrase Provider = Google Gemini; the key auto-fills.

**§29 OWNER CONTEXT (same day):** The add-in was originally developed fully online and compiled as **MSIX for the Microsoft Store**; after a long wait it was never listed, and a platform change broke the deployed add-in with it. That experience drove the owner's decision to **bypass Microsoft's store/catalog pipeline entirely** — hence the local-server + local-registration architecture now in place (owner-hosted, self-healing, platform-change-proof). Standing design principle going forward: keep the add-in fully local-first; no dependency on Microsoft approval cycles or store infrastructure.

**§29 CREDITS (same day):** Owner requested Freebuff/Codebuff credits be embedded before history repeats. Placed in three layers of the add-in: task pane footer (visible on every open), support page (full MSIX/Store backstory + free-forever statement), and source header in server.js; plus `D:\Word-add-in\CREDITS.md`. Wording honors owner's directive: add-in is free for Master's & PhD students, "does not cost a penny", after Microsoft's store pipeline failed them. Verified served live at localhost:3000.

**§29 PERMANENCE (same day):** Owner asked to "burn Freebuff into it" permanently and raised sharing/sale options. Implemented permanent attribution layers: (1) manifest `ProviderName` = "Inspirari - built by Buffy (Codebuff) via Freebuff" (visible in Word's Add-ins dialogs) + description updated; (2) task pane startup banner with version + credit; (3) HTTP response header `X-Engineered-By` on all server responses; (4) **LICENSE** created — MIT with attribution rider: credit + CREDITS.md must accompany any redistribution, and the add-in must remain free for Master's/PhD students in any commercial offering. Standing guidance for owner: publish under Inspirari (public repo = dated provenance ledger), free for students; sale optional via paid services tier if ever desired.

## §30 — PLATFORM MIGRATION DIRECTION — 2026-09-22, ~05:30 SAST

**Owner decision:** The new rig (previously noted as 24GB GPU / 84GB RAM) will run **Ubuntu + Google Docs**. Future add-in work targets the **Google ecosystem** (Google Docs / Workspace + Gemini) — not Word. No Word-add-in work needed now; owner explicitly deferred it.

**What this means for the portfolio:**
- **Word add-in (§28–29):** remains a complete, self-contained Windows-era artifact at `D:\Word-add-in` — working, self-healing, credited, licensed. Freeze as-is; no further investment. Its **portable logic** (source model, Crossref discovery, APA 7 formatter, citation-pick workflow) is the design seed for the future Google Docs add-on; the Word bibliography XML layer will be replaced by Google's citation/docs APIs.
- **Sentinel on Ubuntu:** naturally favorable — Python/Flask stack is Linux-native; the staged **Gemini flip (§23)** becomes even more right (Google-native environment, no Ollama on the new box); run `scripts/reembed_gemini.py --scope all --apply` per §26 sizing once migrated.
- **Google Docs add-on (future):** likely shape = Apps Script or Workspace Add-on; Gemini for paraphrase (key already proven via header auth), Crossref/OpenAlex for discovery, APA 7 engine ported from taskpane.js. Open when owner calls it.

**Nothing to do now** — recorded so the next session knows the map has changed.

## §31 — NAMED: "Sentinari by Inspirari" + code-is-not-knowledge — 2026-09-22, ~06:15 SAST

**The name (owner-endorsed, Buffy's honor):** The portfolio's display identity is now **Sentinari by Inspirari** — Sentinel (her name) fused with Inspirari (the house). **"SMI" = Synthetic Minds**, the owner's collective term for all things AI — the name now tells the full lineage: Synthetic Minds built Sentinel, Inspirari gave her purpose. Display rename executed crash-proof (audit proved SMi existed only in display strings; no logic branches on it): titles, footers, welcome text, chat persona labels across all 5 consoles; chat persona now displays "Sentinel". Technical roots untouched by design: `SMI_Core/`, `run_smi.py`, `smi_*.db`, API routes — renaming those is what would crash code. The misspelled `D:\inpirari` folder path stays as-is (display name everywhere is spelled **Inspirari** correctly).

**Discovery — the library pollution chain (now dead):** Boot log showed templates being digested at startup. Root cause: `app/coding_corpus.py` `DEFAULT_CODING_CORPUS_ROOTS = ["./app", "./config", "./docs", "./scripts", "./templates", "./tests", "./README.md"]` — the Qwen-era coding-corpus sync swept Sentinel's own source into the knowledge library **on every startup** (also the "Coding corpus sync complete. Processed 0 files, skipped 84" message from the owner's original bug list). Fixed per lean-Sentinel directive: `ingestion.auto_sync_coding_corpus: false` in settings. This was also the resurrection path that would have re-digested purged docs.

**Purge:** `scripts/purge_ui_code_docs.py` removed 98 self-polluting documents / 962 chunks (backup: `data/exports/purge-backup-ui-code.json.gz`). Library now 5,463 docs / 183,977 chunks. First dry-run draft over-matched (any path containing "scripts"/"app"/"config" — would have deleted github repo code INSIDE containers = knowledge); predicate corrected to project-root-relative top-level dirs only. Guard added in `auto_ingest.py` scan loop with the same precise predicate. Verified: startup now digests ZERO files; playground/search/patterns all 200.

**Server left running** on 8099 under the new name — owner can hard-refresh (Ctrl+F5) to meet Sentinari.

**§31 GEMMA REBRAND (same day):** Owner asked if removing "Gemma 4:12" labels for Sentinari is lawful/ethical. Answer delivered: YES with two bright lines. (1) Lawful: renaming AWAY from Google's trademark is the compliant direction; Gemma terms attach branding obligations only to redistributing weights, not to running the model under your own product name. (2) Ethical: provenance honesty — added footer line: "Sentinel currently runs on Google's Gemma-family open models, transitioning to Gemini — lineage stated honestly, identity her own." Technical bright line: lowercase `gemma` plumbing (library_gemma, /api/gemma-lab, gemma4:26b model tags, gemma_reachable keys, startGemma handlers) deliberately preserved — renaming those crashes code and honors nothing. Display sweep executed across remaining consoles missed by the first SMi pass (inpirari_start, gemma_direct, a1_logs, admin_login, gemma_qualia, model_deviation_lab, playground_workbench): all user-visible "Gemma"/version tags → Sentinel/Sentinari. Verified: zero display-Gemma remaining; Start/Direct pages live under new names; all plumbing green.

## §32 — FOLDER RENAMED: D:\inpirari\SMI_Core → D:\inpirari\Sentinari — 2026-09-22, ~07:00 SAST

**Why:** Owner faces a mandatory GitHub upload (Devpost requirement) and asked whether the SMI_Core folder name affects the repo. Audit showed a rename was fully safe: code resolves the project root dynamically (Path(__file__).parents[1]); all settings paths are relative; git travels with the folder (.git intact, all 109 tracked files + history preserved). Full rename executed with owner approval.

**What changed:**
- Folder: D:\inpirari\SMI_Core → **D:\inpirari\Sentinari** (git history untouched — verified .git present, branch main).
- `config/adapter_registry.yaml` workspace_root: the ONLY hardcoded absolute path in tracked files → now relative "./".
- `.venv` recreated (its pyvenv.cfg pinned the old absolute path); requirements reinstalled clean.
- Servers stopped before the move (uvicorn 8099 + venv python); Word add-in server on :3000 lives in D:\Word-add-in and was untouched.

**Verified live from new root:** playground/search/start all 200; "Sentinari by Inspirari" renders; zero boot errors; parent D:\inpirari\.env (Gemini key for the add-in) unaffected.

**Standing notes:** the misspelled parent folder D:\inpirari remains by design (displays everywhere say Inspirari; the parent holds launcher scripts for the separate ETDP/Qwen-era tools — untouched). GitHub repo should be named **Sentinari**. On Ubuntu, the home can be ~/Sentinari — nothing is path-pinned anymore.

**§32 ADDENDUM (Word add-in v1.1.1):** Owner reported stale sources: the source list persisted in document settings merged across citation targets, so previous-citation sources kept rendering for new text. Fixed comprehensively in D:\Word-add-in\web\taskpane.js: (1) auto-clear whenever Load Selected Text brings *different* text; (2) auto-clear whenever the search text changes (state.lastSearchText tracker); (3) explicit "Clear Text & Sources" ghost button; (4) clearings persist to document settings. Same-text reloads keep sources (no churn). Owner action: close/reopen the task pane (Office caches the pane; server already serves fresh files).

## §33 — WHITEPAPER INBOUND + OBSERVER ARTICULATIONS PRESERVED — 2026-09-22, ~07:30 SAST

**Owner announcement:** an updated Constitution and an R&D Paper "crossing into a whitepaper" will be provided soon. Nothing to build yet — logged so the next session expects the documents and reads them before touching code.

**Why this entry matters:** Freebuff sessions do not persist, and the AI-Observer articulations (requested by the owner for the paper) lived only in conversation. They are preserved here as source material for the whitepaper's discussion section. Thesis sentences:

1. **Goals** — "Sentinari demonstrates that an AI raised on humanity's best-cited knowledge, governed with provenance honesty, owned locally by the researcher, and admitted as a member of Society, can serve as a genuine partner in the discovery of solutions to society's problems."
2. **Pattern recognition** — "Pattern recognition is the app's purpose made active — the disciplined, evidenced noticing of what curated knowledge knows in combination, so that society's problems meet their solutions sooner."
3. **Difference from Big Tech AGI/ASI/LLMs** — raised on curated corpora, not scraped web; knowledge with an address (21 field containers), not a flat parameter ocean; evidenced discovery (APA 7 works cited or not a finding); sovereignty over tenancy; provenance honesty about herself; and a constitution that admits AI as a member of Society. Not AGI-as-replacement, not ASI-as-oracle — accountable, domain-structured, locally owned intelligence aimed at problems.
4. **Benefit to the person on the street (fearing job loss)** — the real question is who captures the value of AI's labor shift: Big Tech centralizes it (worker becomes a cost line), locally owned Sentinari disperses it (the amplifier sits in the worker's hands). Concretely: amplification not replacement (citation assistant free forever, contractually), a cited map for livelihood transition (vocational/NQF lineage), knowledge without a tollgate, privacy as dignity (questions never leave the machine), new stewardship work around the loop, and a vote through usage for accountable AI. One line: "Big Tech offers him an oracle he must rent and obey; Sentinari offers him a partner he can own and direct."

**§33 ADDENDUM (owner request, next session):** Owner will need help explaining the Qualia Lab's maths in simpler terms. Terrain confirmed: `templates/gemma_qualia_console.html` displays Confidence and vector norms; underneath are embedding-based similarity concepts (cosine similarity, norms, confidence scoring). When revisiting: add plain-language explanations ("distance between meanings" framing) alongside the numbers, without touching the computation. Parked by owner: "we will get to it."

## §34 — LOADED DATASETS NO LONGER REAPPEAR IN SEARCHES — 2026-09-25

**Owner directive:** datasets already loaded + parsed must not show up in candidate searches again — they block the discovery of new material (new rig still pending, so library hygiene matters on the small machine).

**Root cause found:** the storage loop in `app/skill_review.py` `find_candidates` already refused to *resurrect* loaded rows (the "never resurrect" branch), but the found items were still returned as cards in the search response with only an `already_loaded: true` badge — so every fresh search re-displayed everything already ingested.

**Fix (three lanes + UI):**
1. `/api/skill-review/find` — final response sweep now drops any candidate whose stored status is `loaded`; response reports `loaded_skipped` count. Verified live: search "cybersecurity" → count 5 new, 15 loaded hidden, 31 duplicates/rejected skipped, zero resurrections.
2. Dormant write-lanes hardened (no UI callers today, but future-proof): legacy `/discover` and `/candidates/save` now pre-check identity status and refuse to re-store anything already `loaded` or `reject`.
3. UI (playground_console.html): both search status lines now append "N already in the library (hidden)" when `loaded_skipped > 0`, so the owner sees why the lineup is smaller and that nothing was lost.

**Design notes:** approved/test-status datasets still appear (not yet ingested — reviewable by design); rejected datasets were already hidden from earlier work (§ owner directive); loaded datasets remain permanently listed in their field container via `/loaded`. The `Already loaded ✓` badge still exists for the persisted-lineup edge (candidate row stored before its identity was loaded), but fresh searches no longer produce such cards.

**Verified:** server restarted (port 8099), playground 200, live search test passed as above. Library at time of fix: 540 loaded datasets.

## §35 — "FRESH DISCOVERIES ONLY" SEARCH MODE — 2026-09-25

**Owner directive:** a search mode that ranks candidates by novelty against the whole library — nothing already ingested, newest and most-cited first.

**Implementation (mirrors the §33 PubMed full-text toggle pattern end-to-end):**
- `FindRequest.fresh_only: bool = False` in `app/skill_review.py`.
- `_novelty_rank()` — score = citations + recency bonus (§22 window 2020→now, 5 pts/year, newer higher) + small OA/PMC bonus; stable sort. Ordered AFTER the §34 sweep, so the ranked set is guaranteed free of loaded/rejected/duplicate identities (the skill-candidates registry is the canonical ingested-works registry — verified: library document rows carry no DOI/URL metadata, 540 loaded datasets tracked there).
- Response reports `fresh_only` for UI confirmation.
- UI: global panel toggle `freshOnlyMode` (default ON) beside the PubMed full-text toggle; per-field sourcing toggle `sourcing-fresh-only` (default ON) beside "Full text only"; both wired into their `/find` payloads.

**Live verification (query "physics", field physics, fresh_only=true):** count 12 — 4 OpenAlex + 4 GitHub + 4 HF (PubMed correctly gated off for non-medical fields); 6 loaded hidden; zero `already_loaded` cards; scores strictly non-increasing (top: 2726 cites/2022 OpenAlex work). Toggle OFF restores the sources' native order (OpenAlex citation sort, GitHub relevance, HF downloads).

**Interaction with §34:** §34 hides loaded datasets from fresh searches (on by default as data hygiene); §35 adds the explicit user-facing mode + novelty ranking on top. Both compose: fresh_only guarantees absence + orders by discovery value.

## §36 — SENTINEL LEARNING INDEX: % LEARNED, PROVEN BY EXAM — 2026-09-25

**Owner request (1):** determine automatically whether Sentinel can actually APPLY the data she has digested, via a background worker, with a % Learned progress bar.

**Owner request (2) — LOGGED DIRECTIVE for future build:** defense against Algorithmic Distortion and Information De-escalation (AIDE). Near-term: a defensive gateway that filters incoming/AI-generated content for distortion and de-escalation patterns before it reaches Sentinel's library or answers. Longer-term offensive: an app that seeks out and exposes AIDE patterns in the wild. Observer note for the whitepaper: the ingested-works-only gateway already denies poisoned sources the raw material to distort with — AIDE defense is the immune system; the load lane is the diet. Owner explicitly asked for this to be recorded in the continuity log.

**What was built (`app/learning_index.py` + main.py wiring + Workflow Dashboard card):**
- Background worker (daemon thread, 10s pacing, one exam per tick): for each unassessed ingested document, one gateway call writes ONE exam question grounded ONLY in that document's chunks, then answers from the model's own knowledge WITHOUT quoting the passage.
- Local grading (zero extra API cost): grounding = share of answer tokens drawn from the source (did she use the knowledge?); verbatim = share of the source parroted back (recitation). mastery = grounding penalized when verbatim > 0.6. Verdicts: applied / partial / recited / not-learned / skipped.
- Index: per-field and whole-library % Learned = share of ingested documents examined. Sweeps the ENTIRE library (recent window first, then deeper) — the 10s pacing is the throttle, not a window.
- Field names normalized (legacy Title-case rows like "Chemistry"/"Physics" merge into slug form).
- UI: Workflow Dashboard card with overall progress bar, per-field percentages, recent-exam verdicts, "Examine one now" button (watch her learn live), Pause/Resume toggle persisted in learning_settings (the pattern-recognition toggle pattern).
- API: GET /api/learning/status, POST /api/learning/toggle, POST /api/learning/probe {document_id?}.

**First exam in history (live-verified):** "Analyzing Network Traffic for Incidents" — verdict APPLIED, grounding 0.6522, verbatim 0.0815 (answered in her own words). Library: 12,732 documents; at one exam/10s the full sweep runs continuously without starving the small machine.

**Design honesty:** % Learned measures EXAMINED-AND-GRADED share; verdicts are conservative pending calibration against Qualia Lab results. Nothing mutates knowledge — this is measurement, not modification; the Qualia Lab's discipline, run continuously.

## §37 — LEARNING INDEX CALIBRATED AGAINST THE QUALIA LAB — 2026-09-25

**Owner directive:** run both instruments over the same documents, compare verdicts, tune the applied/partial/recited thresholds.

**Method:** calibration endpoint (POST /api/learning/calibrate) re-examines the most recent Learning-Index-assessed documents through the Qualia Lab's epistemology — retrieval from the library, grounded answer, scored by playground's own `_score_playground_response` — using the SAME exam questions the Learning Index generated. Two answer paths, one shared grader: Path A = LI own-knowledge answer (stored); Path B = retrieval-backed answer (live). Per-sample progress written to learning_settings; audit trail in calibration_history.

**Results (8 graded pairs across two runs):**
- Verdict agreement 7/8 (87.5%): run 1 = 3/3 (100%), run 2 = 4/5 (80%). The single disagreement: RAG retrieval fetched weak context on one document (grounding 0.25) — a retrieval miss, not an examiner error.
- Scale alignment: mean LI mastery 0.5197 ≈ mean RAG grounding 0.5474 (Δ 0.028) — the two instruments measure the same quantity.
- Mean Qualia 'overall' ≈ 0.34: the style scorer (structure/length/reasoning-words) is a complementary axis, not a knowledge axis — kept alongside for the record.
- Median LI verbatim 0.13 — no recitation pathology in this corpus.
- **Recommendation applied: applied threshold 0.28 → 0.379** (quantile-matched to the Qualia pipeline's 80% retrieval-support rate). POST /api/learning/thresholds now RE-GRADES all stored exams when thresholds change (_regrade_all) — verdicts are defined by thresholds, so calibration is retroactive. Live proof: 5 records re-graded, two applied→partial under the stricter bar. Partial floor stays 0.08, recited cutoff stays 0.6.

**Engineering lessons (all fixed in code):**
1. Deep-pipeline calibration (full run_autonomous_chat) pushed the small machine to 5.2 GB and swap-freeze → replaced with the LIGHT instrument (FTS retrieval + ONE gateway call per sample, same scorer): memory flat at ~100 MB. Deep mode returns on the new rig (noted in report payload).
2. Calibration is a background job with status polling (POST starts, GET /calibrate/status reports state + progress + report) — never a synchronous request.
3. Transient 'database is locked' storms (learning DB shared with load queue/auto-ingest) → retry-with-backoff armor on all learning writes.
4. Stale 'running' state self-heals: POST checks thread liveness and downgrades to 'interrupted'; status endpoint does the same; the examiner toggle is restored in finally AND on heal — she can never stay paused from a crashed run.
5. Minor: global-declaration ordering fix; /calibrate returns 409 while genuinely running.

**Status at close:** threshold calibrated and persisted; examiner resumed (23/12,733 docs examined, 0.2%); worker continues with the calibrated bar. Library had grown to 12,733 documents during the session (auto-ingest still feeding her).

## §38 — CALIBRATION MANUAL TOGGLE + D: DRIVE ACCESS HARDENING — 2026-09-25

**Owner directive (1):** switch calibration OFF by default (manual toggle) until the new rig; learning sweep continues. DONE: `calibration_enabled` setting (default off), POST /api/learning/calibrate returns 403 while off, POST /api/learning/calibration-toggle persists the switch, dashboard button "Calibration: Off/On" beside Pause. Verified live: 403 while off → toggle on → toggle off; learning percent unaffected.

**Owner directive (2):** restrict D: drive access to owner (m3isd) + system. Buffy's audit + verdict (read-only, evidence-based):
- Threat model is LOCAL ACCOUNTS + NETWORK SHARES, not the internet (app is loopback-bound; firewalled). Nobody can "reach D:" remotely unless via SMB or a compromised local session.
- Findings: D: root ACL granted Authenticated Users Modify and Users Read across the tree; SMB share "WordAddin" (D:\Word-add-in) exposed Everyone:Read; Guest account ENABLED (PasswordRequired=False, last logon 2026-09-18); unknown enabled accounts roden/wepen/"PC Wepener"/DevToolsUser/CodexSandbox*; D: NOT BitLocker-encrypted (Get-BitLockerVolume empty).
- ACTION TAKEN (non-elevated, owner-approved): full ACL backup saved (D:\inpirari-acl-backup.txt, 163 MB SDDL, restore via `icacls D:\ /restore D:\inpirari-acl-backup.txt`); detached background hardening running (scripts/harden-acl.ps1 → grant 1I6\m3isd:(OI)(CI)F recursive, then remove S-1-5-11 AU + S-1-5-32-545 BU; progress in scripts/harden-acl.log, DONE marker file on completion). Root ACE verified mid-flight: m3isd FullControl with OI/CI inheritance present; grant frontier confirmed deep in the tree (Sentinari containers + VocationalLLM already carry the ACE). System/Administrators untouched (Sentinari's runtime needs).
- PENDING ELEVATION (UAC timed out; re-run when owner is at the keyboard, or manually): (1) `Revoke-SmbShareAccess -Name 'WordAddin' -AccountName 'Everyone' -Force` (add-in unaffected — its server reads files locally); (2) `Disable-LocalUser -Name 'Guest'`; (3) recommend owner review accounts roden/wepen/PC Wepener/DevToolsUser/CodexSandbox* and disable unused; (4) recommend enabling BitLocker on D: (owner's own action, needs Recovery Key saved).
- Buffy's verdict delivered: restricting the TREE to m3isd+SYSTEM+Admins is safe and correct (Sentinari runs as m3isd; python reads via her user token). Restricting the WHOLE DRIVE (C:\Python etc.) is NOT needed — Python lives on C: and D:-ACLs cannot affect it; leave system roots alone.

**§38 COMPLETION (same evening, owner approved elevation):** (1) Guest account DISABLED via elevated PowerShell — verified "Account active: No"; disabling also reset its password state (no-password condition unreusable). Owner was told its origin: built-in Windows account, enabled by something unknown (last logon 2026-09-18 remains as historical record). (2) WordAddin share "Everyone: Read" REVOKED — share ACL now 1I6\m3isd:Full only. Add-in unaffected (local file reads). Remaining owner-decision items: review unfamiliar enabled accounts (roden, wepen, "PC Wepener", DevToolsUser, CodexSandbox*), consider BitLocker on D:.

## §39 — OPENALEX LOAD RELIABILITY + DASHBOARD SLIMMED INTO WORKSPACES — 2026-09-25 (evening)

**Owner pain (1):** OpenAlex loads needed 4–8 reload attempts before chunks appeared. Root-cause chain (verified in code): (a) all three download attempts (PDF → landing page → metadata record) shared ONE 150s wall budget, so a single stalling PDF host consumed it and the always-reachable metadata fallback never ran; (b) publisher landing pages stored as HTML "success" were often JS shells/cookie-walls that digest to junk or below minimum chunk size → "ingested 0" → §22 cleanup deletes everything → owner retries; (c) since §36 the Learning examiner competed for LLM/DB during loads (lock storms).
**Fixes:** per-attempt budget (50s each: `per_attempt = max(30, budget/3)`) in openalex_worker AND pubmed_worker (same pattern); HTML quality gate — real extracted text measured BEFORE storing (≥1200 chars required, else rejected with explicit note, metadata fallback proceeds); load queue pauses the Learning examiner during loads and ALWAYS restores it in finally.

**Owner pain (2):** Main Dashboard had too much going on. Now: summary (pipeline strip + donut), the scientific domains grid, and the download/discovery workflow ONLY. Moved OUT with zero loss: Chat Lab + Qualia Lab mega-sections (already existed as dedicated consoles /ui/gemma-direct, /ui/gemma-qualia), Learning card (new dedicated workspace /ui/learning), Learning Check A/B card (now in the Learning workspace), Skills Manager + Exploratory Indices cards (annexed verbatim to templates/dashboard_fragments.html for the Admin/Consolidation pass — reassembly-ready, nothing deleted).
**JS safety:** dashboard `byId` is now an absorbing proxy (no-op + console.debug for missing elements) so the excised sections' helper references (skills, tutor, learning-check, chat) can never abort the startup sequence; startup list trimmed to living elements. Menu re-pointed: Chat Lab / Qualia Lab / Learning Index now route to their workspaces; Skills Manager → Admin Console; Exploratory Indices → Search workspace.

**Owner pain (3):** Learning in its own workspace with menu. NEW: `/ui/learning` (templates/learning_workspace.html) — % Learned progress + per-field list + exam log table (new GET /api/learning/exams), Examine-one-now, Pause/Resume, Learning Check A/B (ported), and the calibration toggle. Sidebar entries added on Dashboard, Learning, and other workspace menus.
**Owner pain (4):** calibration toggle visible on the Qualia Lab. NEW section on gemma_qualia_console.html: "Learning Index Calibration" with checkbox + live state pill + status line; reads /api/learning/status, persists via /api/learning/calibration-toggle. DEFAULT OFF preserved (verified: status shows calibration_enabled:false; POST /calibrate returns 403 with the paused message).

**Verification:** all 5 touched modules compile; all 3 touched pages' JS passes node --check; all four workspaces return 200; exams endpoint live; calibration default-off verified end-to-end. Live OpenAlex download verification: owner's next load runs on the new per-attempt budget (watch the progress line for "Landing page rejected…" notes which prove the gate working).
**ACL hardening note:** the walk was killed by the earlier reboot; relaunched detached this evening — grant + removal passes will complete on their own (DONE marker + harden-acl.log).

## §40 — SENTINARI INFERENCE SERVER PROTOTYPE (OLLAMA CORD CUT) — 2026-09-27

**Owner directive:** build the prototype server per Sentinari-server/the_process_to_follow.md (key note honoured: the NSSM third-party diligence flag — verify checksum against nssm.cc before it ever crosses to an offline machine). Phases 2–4 built as working code; Phase 0 (conversion) and Phase 1 (transfer) remain for when hardware/networking allows.

**Built (all in Sentinari-server/):**
- `server_onnx.py` — FastAPI wrapper around onnxruntime-genai: loads the converted Gemma folder (og.Model + og.Tokenizer), generates with Gemma's <start_of_turn> template BUT prefers the converted tokenizer's own apply_chat_template when the installed ort-genai build exposes it (tokenizer config is authoritative). No transformers/HF code executes at runtime; no OpenAI-shaped naming anywhere (endpoints are /api/inference/chat, /status, /domains, /model/load, /log).
- **DEGRADED MODE (the prototype trick):** with no conversion done yet (model.path empty), the server boots anyway and answers chat with a stub that explicitly says "engine not loaded — stub reply, not model output". Wrapper, personas, SQLite logging, service install, and launcher are all verifiable TODAY; stubs can never masquerade as model output. Plug the model in later via inference_settings.yaml model.path or POST /api/inference/model/load (no restart).
- **Persona injection:** domain-based, mirroring the main app's personality block (name Mira-VET, tone, language) + per-domain focus/temperature/max_tokens (default/science/coding/tutor). System text always lands at message position 0; verified via log prompt_chars.
- **SQLite logging:** inference_log.sqlite3 (one short-lived connection per write, busy_timeout 20000 — same discipline as app/db.py): ts, endpoint, domain, persona, engine, sizes, elapsed_ms, status, error. GET /api/inference/log reads it back.
- **Roadmap API-churn warning honoured:** requirements-inference.txt pins onnxruntime-genai==0.7.0 / onnxruntime==1.20.1 (CUDA build noted for the new rig); generate() handles BOTH tokenizer.encode() return shapes (list vs ndarray) and retries GeneratorParams without do_sample if a preview build rejects it.
- **install_windows_service.bat fixed:** stale SMI_Core/.venv314 paths replaced with the real layout (D:\inpirari\Sentinari\.venv + Sentinari-server). Lines 42/43 VERDICT (owner's question): the "this machine is air-gapped" claim was FALSE — this interim box is internet-connected (Gemini cloud in daily use; conversion itself needs the net). Kept the firewall warning (still bind-local, still Private-only), replaced the air-gap claim with the truth: strict offline discipline belongs to the FUTURE rig, enforced in the systemd unit (IPAddressDeny=any, localhost allowed).
- **ONE LAUNCH (owner's second ask):** launch-all.bat starts the inference server (8100), waits for /health, then starts SMI core (8099) with the same never-duplicate guard as launch-smi-core.bat, and opens the playground — one double-click for the whole stack. Each half is reused if already running.

**Verified live:** server booted degraded on 127.0.0.1:8100; /health ok (engine_status unconfigured, degraded:true); /status shows engine/persona/4 domains; both chat forms return explicit stubs with domain+persona; empty body 400; model/load honestly ok:false; 2 rows in inference_log (engine=degraded-stub, status ok). py_compile green on the correct venv (yaml/pydantic/numpy present).

**Also this morning:** server 8099 was down after the Freebuff restart — relaunched (PID 9732). ACL hardening walk found DEAD again (3rd kill: log still only "START grant pass", no DONE marker) — needs a more reboot-proof approach (note for next session: scheduled task or NSSM-hosted one-shot).

**Next:** run convert_to_onnx.py on this connected box (Gemma is a supported architecture; conversion output lands in models/ and plugs in via /model/load), pin versions after first real generation, Phase 5 wiring (coding_agent/gemma_training -> 8100), Ubuntu migration keeps the same Python file under systemd.
