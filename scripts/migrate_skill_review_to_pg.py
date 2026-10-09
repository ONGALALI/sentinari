import sqlite3
import psycopg2
from psycopg2.extras import execute_values

PG_URL = "postgresql://postgres:Sentinari_2026_Cloud_Db!@136.71.184.96:5432/sentinari"

def migrate():
    pg_conn = psycopg2.connect(PG_URL)
    pg_cur = pg_conn.cursor()

    print("[1] Creating skill_review_candidates in Cloud SQL...")
    pg_cur.execute("""
    CREATE TABLE IF NOT EXISTS skill_review_candidates (
        id SERIAL PRIMARY KEY,
        source_type TEXT NOT NULL,
        source_url TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        scientific_field TEXT NOT NULL DEFAULT '',
        target_persona TEXT NOT NULL DEFAULT 'gemma',
        license TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        discovered_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TEXT NOT NULL DEFAULT '',
        loaded_document_id INTEGER,
        loaded_title TEXT NOT NULL DEFAULT '',
        loaded_at TEXT NOT NULL DEFAULT '',
        identity_key TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_skill_review_status ON skill_review_candidates(status, discovered_at DESC);
    CREATE INDEX IF NOT EXISTS idx_skill_review_identity ON skill_review_candidates(identity_key);
    """)
    pg_conn.commit()

    s_conn = sqlite3.connect("data/smi_vocationalllm.db")
    s_cur = s_conn.cursor()
    s_cur.execute("""
        SELECT id, source_type, source_url, title, description, scientific_field, target_persona,
               license, status, metadata_json, discovered_at, reviewed_at, loaded_document_id,
               loaded_title, loaded_at, identity_key
        FROM skill_review_candidates;
    """)
    rows = s_cur.fetchall()
    print(f"[2] Migrating {len(rows)} skill review candidates...")

    execute_values(
        pg_cur,
        """
        INSERT INTO skill_review_candidates 
            (id, source_type, source_url, title, description, scientific_field, target_persona,
             license, status, metadata_json, discovered_at, reviewed_at, loaded_document_id,
             loaded_title, loaded_at, identity_key)
        VALUES %s
        ON CONFLICT (source_url) DO UPDATE SET
            status = EXCLUDED.status,
            loaded_document_id = EXCLUDED.loaded_document_id,
            loaded_title = EXCLUDED.loaded_title,
            loaded_at = EXCLUDED.loaded_at,
            identity_key = EXCLUDED.identity_key;
        """,
        rows
    )
    pg_conn.commit()

    # Update sequence
    pg_cur.execute("SELECT setval('skill_review_candidates_id_seq', (SELECT MAX(id) FROM skill_review_candidates));")
    pg_conn.commit()

    pg_cur.execute("SELECT count(*), count(case when status='loaded' then 1 end) FROM skill_review_candidates;")
    total, loaded = pg_cur.fetchone()
    print(f"[+] Done: {total} total candidates, {loaded} loaded datasets in Cloud SQL!")

    pg_conn.close()
    s_conn.close()

if __name__ == "__main__":
    migrate()
