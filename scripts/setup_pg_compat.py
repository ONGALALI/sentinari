"""Set up SQLite compatibility helpers in PostgreSQL."""
import psycopg2

def setup_compat(pg_url: str):
    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()
    # 1. ifnull function compatible with SQLite
    cur.execute("""
        CREATE OR REPLACE FUNCTION ifnull(anycompatible, anycompatible)
        RETURNS anycompatible LANGUAGE sql IMMUTABLE AS $$
            SELECT COALESCE($1, $2);
        $$;
    """)
    conn.commit()
    cur.execute("SELECT ifnull(NULL, 'sqlite_compat_works');")
    res = cur.fetchone()[0]
    print(f"[+] IFNULL function installed and verified: {res}")
    conn.close()

if __name__ == "__main__":
    import os
    url = os.environ.get("DATABASE_URL", "postgresql://postgres:Sentinari_2026_Cloud_Db!@136.71.184.96:5432/sentinari")
    setup_compat(url)
