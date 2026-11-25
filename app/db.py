# ============================================================================
#  db —— SQLite：对话、任务、视频记录、AI 供应商、API Key
#
#  项目/系列的元信息在 JSON、内容在 Markdown（见 core/store.py），不进数据库。
#  每次操作一个短连接（WAL），没有连接池、没有 ORM。
# ============================================================================
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path


def now_iso(plus_minutes: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(minutes=plus_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


SCHEMA = """
CREATE TABLE IF NOT EXISTS owner (
  id INTEGER PRIMARY KEY CHECK (id = 1), sub TEXT NOT NULL, email TEXT, name TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, prefix TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE,
  scopes TEXT NOT NULL, created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS providers (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL, api_key BLOB NOT NULL,
  model TEXT NOT NULL, is_default INTEGER NOT NULL DEFAULT 0,
  test_ok INTEGER, test_detail TEXT, tested_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS conv_project ON conversations (project_id);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, model TEXT, error TEXT,
  files TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS msg_conv ON messages (conversation_id);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, project_id TEXT NOT NULL, release INTEGER NOT NULL, status TEXT NOT NULL,
  feedback TEXT, claim TEXT, worker TEXT, lease_until TEXT, progress TEXT, error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_task ON tasks (project_id)
  WHERE status IN ('queued', 'working', 'review');
CREATE TABLE IF NOT EXISTS videos (
  id INTEGER PRIMARY KEY, project_id TEXT NOT NULL, task_id INTEGER NOT NULL, version INTEGER NOT NULL,
  size INTEGER NOT NULL, note TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE (project_id, version)
);
"""


class DB:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def all(self, sql: str, *args) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def one(self, sql: str, *args) -> dict | None:
        rows = self.all(sql, *args)
        return rows[0] if rows else None

    def run(self, sql: str, *args) -> int:
        """返回新行 id。"""
        with self.conn() as c:
            return c.execute(sql, args).lastrowid or 0

    def changed(self, sql: str, *args) -> int:
        """返回受影响的行数。"""
        with self.conn() as c:
            return c.execute(sql, args).rowcount
