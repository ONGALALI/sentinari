# Sentinari Enhancement Roadmap

## Phase 1 — Stabilize the local runtime

- Confirm the local SQLite knowledge database is the canonical source of truth
- Keep the local gateway on a single port and verify health/search endpoints
- Keep provider policy fail-closed and local-only by default
- Add a local operational dashboard to show health, tables, and provider status
- Remove or isolate any accidental remote provider access paths

## Phase 2 — Strengthen observability

- Expose a clear local status page with DB path, table count, and search readiness
- Add search quality diagnostics and document count summaries
- Add chunk metadata visibility for document inspection
- Add local-only logging for queries, access events, and provider policy decisions

## Phase 3 — Improve the knowledge workflow

- Add document ingestion validation
- Add chunk quality scoring and indexing health checks
- Add metadata normalization rules for scientific fields and sources
- Add bookmarking, tagging, and local classification support

## Phase 4 — Governance and control

- Keep the constitution as runtime behavior, not just documentation
- Formalize provider allow/deny decisions in config or module-level policy
- Add explicit local admin controls for policy toggles
- Add document access audit trails for controlled local use

## Phase 5 — Public-facing presentation layer

- Keep GitHub as the public repo and project showcase only
- Create a safe static landing page for external viewers
- Show screenshots, architecture diagrams, and a snapshot of the project
- Avoid exposing private data, runtime secrets, or live backend endpoints

## Phase 6 — Advanced productization

- Expand the dashboard with operational widgets and search analytics
- Add local user roles and permission layers if needed
- Evaluate optional self-hosted model integrations only when governance approves them
- Consider a paid hosted environment only after a separate security and architecture review

## Priority order

1. Lock down provider policy
2. Stabilize local dashboard
3. Improve search observability
4. Strengthen document metadata management
5. Build a public showcase layer
6. Plan any hosted environment separately from the private runtime
