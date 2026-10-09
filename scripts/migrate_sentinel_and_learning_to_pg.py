import sqlite3
import psycopg2
from psycopg2.extras import execute_values

PG_URL = "postgresql://postgres:Sentinari_2026_Cloud_Db!@136.71.184.96:5432/sentinari"

def migrate():
    pg_conn = psycopg2.connect(PG_URL)
    pg_cur = pg_conn.cursor()

    # 1. sentinel_domains
    print("[1] Migrating sentinel_domains...")
    pg_cur.execute("""
    CREATE TABLE IF NOT EXISTS sentinel_domains (
        id SERIAL PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    """)
    sqlite_conn = sqlite3.connect("data/sentinari.db")
    s_cur = sqlite_conn.cursor()
    s_cur.execute("SELECT slug, name, description FROM sentinel_domains;")
    domains = s_cur.fetchall()
    for slug, name, desc in domains:
        pg_cur.execute("""
            INSERT INTO sentinel_domains (slug, name, description)
            VALUES (%s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description;
        """, (slug, name, desc))
    pg_conn.commit()
    print(f"  Migrated {len(domains)} domains.")

    # 2. sentinel_scientific_fields
    print("[2] Migrating sentinel_scientific_fields...")
    pg_cur.execute("""
    CREATE TABLE IF NOT EXISTS sentinel_scientific_fields (
        id SERIAL PRIMARY KEY,
        domain_slug TEXT NOT NULL,
        field_name TEXT NOT NULL,
        field_slug TEXT NOT NULL UNIQUE,
        detail TEXT NOT NULL DEFAULT '',
        taxonomy_path TEXT NOT NULL DEFAULT '',
        documents INTEGER NOT NULL DEFAULT 0,
        chunks INTEGER NOT NULL DEFAULT 0,
        bytes_total BIGINT NOT NULL DEFAULT 0,
        last_ingest_at TEXT,
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_sentinel_fields_domain ON sentinel_scientific_fields(domain_slug);
    """)

    # Get the latest row for each distinct field_slug from sentinari.db
    s_cur.execute("""
        SELECT domain_slug, field_name, field_slug, detail, taxonomy_path, documents, chunks, bytes_total, last_ingest_at
        FROM sentinel_scientific_fields
        WHERE id IN (
            SELECT MAX(id) FROM sentinel_scientific_fields GROUP BY field_slug
        );
    """)
    fields = s_cur.fetchall()
    for row in fields:
        pg_cur.execute("""
            INSERT INTO sentinel_scientific_fields 
                (domain_slug, field_name, field_slug, detail, taxonomy_path, documents, chunks, bytes_total, last_ingest_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (field_slug) DO UPDATE SET
                domain_slug = EXCLUDED.domain_slug,
                field_name = EXCLUDED.field_name,
                detail = EXCLUDED.detail,
                taxonomy_path = EXCLUDED.taxonomy_path,
                documents = EXCLUDED.documents,
                chunks = EXCLUDED.chunks,
                bytes_total = EXCLUDED.bytes_total,
                last_ingest_at = EXCLUDED.last_ingest_at;
        """, row)
    pg_conn.commit()
    print(f"  Migrated {len(fields)} scientific fields.")

    # Refresh the actual document and chunk counts from live Postgres documents & chunks tables
    print("[2b] Re-syncing sentinel_scientific_fields counts from live PG documents & chunks...")
    pg_cur.execute("""
        UPDATE sentinel_scientific_fields f
        SET
            documents = COALESCE((SELECT COUNT(1) FROM documents d WHERE d.scientific_field = f.field_slug), 0),
            chunks = COALESCE((SELECT COUNT(1) FROM chunks c JOIN documents d ON d.id = c.document_id WHERE d.scientific_field = f.field_slug), 0),
            bytes_total = COALESCE((SELECT SUM(d.raw_char_count) FROM documents d WHERE d.scientific_field = f.field_slug), 0);
    """)
    pg_conn.commit()

    # 3. learning_settings
    print("[3] Migrating learning_settings...")
    pg_cur.execute("""
    CREATE TABLE IF NOT EXISTS learning_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    """)
    smi_conn = sqlite3.connect("data/smi_vocationalllm.db")
    smi_cur = smi_conn.cursor()
    smi_cur.execute("SELECT key, value FROM learning_settings;")
    settings_rows = smi_cur.fetchall()
    for k, v in settings_rows:
        pg_cur.execute("""
            INSERT INTO learning_settings (key, value)
            VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """, (k, v))
    pg_conn.commit()
    print(f"  Migrated {len(settings_rows)} learning settings.")

    # 4. learning_assessments
    print("[4] Migrating learning_assessments...")
    pg_cur.execute("""
    CREATE TABLE IF NOT EXISTS learning_assessments (
        id SERIAL PRIMARY KEY,
        document_id INTEGER NOT NULL,
        scientific_field TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        question TEXT NOT NULL DEFAULT '',
        answer TEXT NOT NULL DEFAULT '',
        grounding_score REAL NOT NULL DEFAULT 0,
        verbatim_score REAL NOT NULL DEFAULT 0,
        mastery REAL NOT NULL DEFAULT 0,
        verdict TEXT NOT NULL DEFAULT '',
        assessed_at TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_learning_field ON learning_assessments(scientific_field);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_learning_doc ON learning_assessments(document_id);
    """)

    smi_cur.execute("""
        SELECT document_id, scientific_field, title, question, answer, grounding_score, verbatim_score, mastery, verdict, assessed_at
        FROM learning_assessments;
    """)
    assessments = smi_cur.fetchall()
    print(f"  Found {len(assessments)} assessments to load...")
    
    batch_size = 5000
    for i in range(0, len(assessments), batch_size):
        batch = assessments[i:i + batch_size]
        execute_values(
            pg_cur,
            """
            INSERT INTO learning_assessments 
                (document_id, scientific_field, title, question, answer, grounding_score, verbatim_score, mastery, verdict, assessed_at)
            VALUES %s
            ON CONFLICT (document_id) DO NOTHING;
            """,
            batch
        )
        pg_conn.commit()
        print(f"  Loaded {min(i + batch_size, len(assessments))} / {len(assessments)} assessments.")

    # Summary verification
    print("\n--- VERIFICATION ---")
    for t in ['sentinel_domains', 'sentinel_scientific_fields', 'learning_settings', 'learning_assessments']:
        pg_cur.execute(f"SELECT COUNT(*) FROM {t};")
        print(f"Postgres {t}: {pg_cur.fetchone()[0]} rows")

    pg_cur.execute("SELECT field_slug, documents, chunks FROM sentinel_scientific_fields ORDER BY documents DESC LIMIT 5;")
    print("Top 5 fields:")
    for r in pg_cur.fetchall():
        print(f"  {r[0]}: {r[1]} docs, {r[2]} chunks")

    pg_cur.execute("SELECT COUNT(*), SUM(CASE WHEN verdict = 'applied' THEN 1 ELSE 0 END) FROM learning_assessments;")
    res = pg_cur.fetchone()
    print(f"Learning assessments total: {res[0]}, Applied: {res[1]}")

    pg_conn.close()
    sqlite_conn.close()
    smi_conn.close()

if __name__ == "__main__":
    migrate()
