-- Sentinari Cloud Cutover Schema (PostgreSQL 16 + pgvector)
-- Eliminates SQLite file write-locks permanently.
-- Retains Article V Rights of Every Observation, Qualia State, and Pattern Discovery.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- 1. KNOWLEDGE LIBRARY: Documents & Chunks
CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT,
    title TEXT,
    source_type TEXT,
    source_url TEXT,
    source_path TEXT,
    checksum TEXT NOT NULL,
    archive_path TEXT,
    module TEXT,
    topic TEXT,
    scientific_field TEXT,
    vocational_discipline TEXT,
    source_collection TEXT,
    language TEXT DEFAULT 'en',
    license TEXT,
    published_date TEXT,
    authors TEXT,
    publisher TEXT,
    document_metadata JSONB DEFAULT '{}'::jsonb,
    raw_char_count INT DEFAULT 0,
    priority INT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_field ON documents(scientific_field);
CREATE INDEX IF NOT EXISTS idx_documents_checksum ON documents(checksum);
CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents(source_collection);

CREATE TABLE IF NOT EXISTS chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    token_estimate INT DEFAULT 0,
    chunk_hash TEXT NOT NULL DEFAULT '',
    metadata JSONB DEFAULT '{}'::jsonb,
    embedding vector(768), -- Strict binary vector coordinate replacing SQLite JSON bloat
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id, chunk_index);
-- Note: HNSW and FTS indexes are built in post-migration step for maximum bulk loading speed

-- 2. ARTICLE V KNOWLEDGE MATRIX (The Rights of Every Observation)
CREATE TABLE IF NOT EXISTS article_v_knowledge (
    observation_id TEXT PRIMARY KEY,
    source_db TEXT NOT NULL DEFAULT 'sentinari',
    source_table TEXT NOT NULL,
    source_rowid BIGINT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scientific_field TEXT,
    falsifiable_claims JSONB NOT NULL DEFAULT '[]'::jsonb,
    numerical_metrics JSONB NOT NULL DEFAULT '[]'::jsonb,
    epistemic_confidence REAL NOT NULL DEFAULT 1.0,
    provenance_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_article_v_source ON article_v_knowledge(source_table, source_rowid);
CREATE INDEX IF NOT EXISTS idx_article_v_field ON article_v_knowledge(scientific_field);
CREATE INDEX IF NOT EXISTS idx_article_v_claims_gin ON article_v_knowledge USING gin(falsifiable_claims);

-- 3. PATTERN DISCOVERY STORE
CREATE TABLE IF NOT EXISTS pattern_entities (
    id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mention_count INT NOT NULL DEFAULT 1,
    UNIQUE(entity_type, normalized_name)
);

CREATE TABLE IF NOT EXISTS pattern_relations (
    id BIGSERIAL PRIMARY KEY,
    source_entity_id BIGINT NOT NULL REFERENCES pattern_entities(id),
    target_entity_id BIGINT NOT NULL REFERENCES pattern_entities(id),
    relation_type TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mention_count INT NOT NULL DEFAULT 1,
    UNIQUE(source_entity_id, target_entity_id, relation_type)
);

CREATE TABLE IF NOT EXISTS patterns (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    pattern_type TEXT NOT NULL DEFAULT 'general',
    fields_involved JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'candidate',
    template_key TEXT NOT NULL DEFAULT '',
    review_note TEXT NOT NULL DEFAULT '',
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    activated_at TIMESTAMPTZ,
    evolution_history JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS pattern_evidence (
    id BIGSERIAL PRIMARY KEY,
    pattern_id BIGINT NOT NULL REFERENCES patterns(id) ON DELETE CASCADE,
    document_id BIGINT,
    chunk_id BIGINT,
    document_title TEXT NOT NULL DEFAULT '',
    field_slug TEXT NOT NULL DEFAULT '',
    chunk_text TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. OPERATIONAL STATE & QUALIA MEMORY
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    mode TEXT DEFAULT 'standard',
    scientific_field TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    qualia_state JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qualia_history (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT,
    step_index INT DEFAULT 0,
    s_vector JSONB NOT NULL,
    a_vector JSONB NOT NULL,
    q_vector JSONB NOT NULL,
    stability_index REAL NOT NULL,
    anxiety_level REAL NOT NULL,
    gemma_gate_open BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
