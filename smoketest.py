import sqlite3

db_path = r"D:\Sentinari\data\sentinari.db"

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

print("DB connected:", db_path)

tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
).fetchall()

print("Table count:", len(tables))
print("Sample tables:", [r["name"] for r in tables[:10]])

doc_count = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
print("Document count:", doc_count)

sample = conn.execute(
    "SELECT id, title, scientific_field FROM documents ORDER BY id DESC LIMIT 5"
).fetchall()

print("Sample documents:")
for row in sample:
    print(dict(row))

conn.close()