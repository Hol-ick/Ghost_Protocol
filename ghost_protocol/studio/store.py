"""Small, transactional JSON document store isolated from the legacy database."""
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


class StudioStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'studio.sqlite3'
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS documents (kind TEXT, id TEXT, payload TEXT NOT NULL, updated TEXT, PRIMARY KEY(kind,id))')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            with conn:
                yield conn
        finally:
            conn.close()

    def get(self, kind, id):
        with self.connect() as conn:
            row = conn.execute('SELECT payload FROM documents WHERE kind=? AND id=?', (kind, id)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind):
        with self.connect() as conn:
            rows = conn.execute('SELECT payload FROM documents WHERE kind=? ORDER BY updated DESC, id DESC', (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, kind, id, payload):
        with self.connect() as conn:
            conn.execute('INSERT INTO documents VALUES (?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,updated=excluded.updated',
                         (kind, id, json.dumps(payload, ensure_ascii=False), now()))
