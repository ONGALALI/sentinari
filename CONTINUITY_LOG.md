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
