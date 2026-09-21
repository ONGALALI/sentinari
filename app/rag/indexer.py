import os
import sqlite3
import json
import time

try:
    import numpy as np
except Exception:
    np = None

try:
    import requests
except Exception:
    requests = None

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(ROOT, 'data', 'vocationalllm.db')
INDEX_DIR = os.path.join(ROOT, 'data', 'rag_index')

os.makedirs(INDEX_DIR, exist_ok=True)

OLLAMA_BASE = os.environ.get('SMI_LLM_BASE', 'http://127.0.0.1:11434')
EMBED_ENDPOINTS = ['/api/embeddings', '/api/embed']


def get_embedding_api():
    for p in EMBED_ENDPOINTS:
        url = OLLAMA_BASE.rstrip('/') + p
        try:
            if requests:
                r = requests.options(url, timeout=3)
                if r.status_code in (200, 204, 404, 405):
                    return url
        except Exception:
            continue
    return None


def scan_text_columns(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    candidates = []
    for t in tables:
        try:
            cur.execute(f"PRAGMA table_info('{t}')")
            cols = [r[1] for r in cur.fetchall()]
        except Exception:
            continue
        # sample some rows to detect text-like columns
        try:
            cur.execute(f"SELECT * FROM {t} LIMIT 20")
            rows = cur.fetchall()
        except Exception:
            rows = []
        for c in cols:
            is_text = False
            # name hint
            if any(x in c.lower() for x in ('text', 'content', 'body', 'chunk', 'raw', 'payload', 'doc', 'note', 'summary')):
                is_text = True
            # inspect sampled values
            if not is_text and rows:
                for r in rows:
                    try:
                        val = r[cols.index(c)] if isinstance(cols, list) else r[c]
                    except Exception:
                        val = None
                    if isinstance(val, str) and len(val) > 40:
                        is_text = True
                        break
            if is_text:
                candidates.append((t, c))
    return candidates


def build_index(limit_per_table=1000):
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    candidates = scan_text_columns(conn)
    if not candidates:
        print('No candidate text columns found in DB')
        return
    samples = []
    for t, c in candidates:
        try:
            cur.execute(f"SELECT rowid, {c} FROM {t} WHERE {c} IS NOT NULL LIMIT {limit_per_table}")
            for row in cur.fetchall():
                rowid, text = row
                if not text:
                    continue
                if isinstance(text, bytes):
                    try:
                        text = text.decode('utf-8', errors='ignore')
                    except Exception:
                        continue
                if len(text) < 20:
                    continue
                samples.append({'table': t, 'col': c, 'rowid': rowid, 'text': text})
        except Exception as e:
            print('scan error', t, c, e)

    embed_api = get_embedding_api()
    if not embed_api:
        print('No embedding endpoint detected on', OLLAMA_BASE)
        conn.close()
        return

    batch = []
    embeddings = []
    meta = []
    for i, s in enumerate(samples, 1):
        batch.append(s['text'])
        meta.append({'table': s['table'], 'col': s['col'], 'rowid': s['rowid']})
        if len(batch) >= 16 or i == len(samples):
            payload = {'model': 'nomic-embed-text', 'input': batch}
            try:
                r = requests.post(embed_api, json=payload, timeout=120)
                j = r.json()
                embs = j.get('embeddings') or j.get('data') or j
                for e in embs:
                    if isinstance(e, dict) and 'embedding' in e:
                        embeddings.append(e['embedding'])
                    elif isinstance(e, list):
                        embeddings.append(e)
                batch = []
            except Exception as ex:
                print('embedding failed', ex)
                break

    if not embeddings:
        print('No embeddings produced')
        conn.close()
        return

    if np is None:
        print('numpy required to store embeddings')
        conn.close()
        return

    arr = np.array(embeddings, dtype=np.float32)
    emb_path = os.path.join(INDEX_DIR, 'embeddings.npy')
    meta_path = os.path.join(INDEX_DIR, 'meta.json')
    np.save(emb_path, arr)
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)
    print('Index built:', arr.shape, 'saved to', INDEX_DIR)
    conn.close()


if __name__ == '__main__':
    start = time.time()
    build_index()
    print('done in', time.time() - start)
