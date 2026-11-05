# CREDITS

## Sentinari 
**Concept, vision, and direction** — Pierre Wepener
- The Sentinel architecture, scientific-field Guardians, and the Constitution (DOC-0) and Sentinel V2 design documents.

**Engineering (2026)** — 
- **Scientific Dataset Discovery & Review** — Curated candidate data sets manually apptoved for further analysis. CREDITS per scientific field; candidate queue with Approve / Reject / Test; load-with-progress ingestion; permanent per-field loaded-dataset registry; HTML preview and PDF download/export.
- **Ingestion hardening** — direct-from-candidate-id ingest flow, scientific-field slug healing, SQLite busy-lock resilience, honest skip-vs-fail reporting in the coding-corpus sync, and a fix for taxonomy enrichment across library/main database connections.
- **Provider-agnostic LLM gateway** (`app/llm_gateway.py`) — Sentinel's umbilical cord to Ollama cut: Ollama, Google Gemini, and OpenAI-compatible providers, hot-swappable via `config/settings.yaml`, with automatic fallback chains (proven live with Ollama fully down, Gemini carrying the request) and transient-503 retries.
- **Sentinel Pattern-Recognition MVP** (`app/pattern_store.py`, `app/pattern_worker.py`, `app/pattern_api.py`) — pattern store implementing the Constitution's Article V observation anatomy (identity, source, timestamp, evidence, relationships, confidence, contradictions, evolution history, unresolved questions); entity/relation extraction through the gateway; a template registry with guarded schema auto-migration; synthesis proposals; and the Pattern Recognition Lab in the playground with the same Approve / Reject / Test lifecycle.
- Live-verified end-to-end: (Drafting the Constitution) produced grounded candidate patterns with per-claim evidence.

