"""SQLite storage: workflows, execution history and encrypted credentials.

The class is synchronous (sqlite3 is fast for this workload) and thread-safe. The one
async method, ``get_credential``, makes ``Database`` usable directly as the engine's
``CredentialProvider``::

    db = Database.open_default()
    engine = WorkflowEngine(credentials=db)
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from engine.errors import CredentialNotFoundError
from engine.models import ExecutionResult, WorkflowDefinition, utcnow

from .vault import DpapiKeyStore, KeyStore, Vault

MIGRATIONS: list[str] = [
    # v1
    """
    CREATE TABLE workflows (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        definition  TEXT NOT NULL,
        active      INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE TABLE executions (
        id            TEXT PRIMARY KEY,
        workflow_id   TEXT NOT NULL,
        workflow_name TEXT NOT NULL,
        status        TEXT NOT NULL,
        error         TEXT,
        started_at    TEXT NOT NULL,
        finished_at   TEXT,
        result        TEXT NOT NULL
    );
    CREATE INDEX idx_executions_workflow ON executions (workflow_id, started_at DESC);
    CREATE TABLE credentials (
        name        TEXT PRIMARY KEY,
        type        TEXT NOT NULL DEFAULT 'generic',
        data        BLOB NOT NULL,
        fields      TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    """,
    # v2
    """
    CREATE TABLE settings (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    """,
]


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "AutomationEngine"


class Database:
    def __init__(self, path: str | Path, key_store: KeyStore | None = None) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        if key_store is None:
            if self.path == ":memory:":
                raise ValueError("an in-memory database needs an explicit key_store")
            key_store = DpapiKeyStore(Path(self.path).with_suffix(".key"))
        self._vault = Vault(key_store)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    @classmethod
    def open_default(cls) -> Database:
        return cls(default_data_dir() / "data.db")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def _migrate(self) -> None:
        version = self._query("PRAGMA user_version")[0][0]
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            with self._lock:
                # executescript commits implicitly, so run it in its own explicit transaction
                self._conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version={number};\nCOMMIT;")

    # ------------------------------------------------------------------ workflows

    def save_workflow(self, workflow: WorkflowDefinition, active: bool | None = None) -> None:
        now = utcnow().isoformat()
        with self._tx() as c:
            c.execute(
                """INSERT INTO workflows (id, name, description, definition, active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description,
                       definition=excluded.definition, updated_at=excluded.updated_at,
                       active=COALESCE(?, workflows.active)""",
                (workflow.id, workflow.name, workflow.description, workflow.model_dump_json(),
                 int(bool(active)), now, now, None if active is None else int(active)),
            )

    def get_workflow(self, workflow_id: str) -> WorkflowDefinition | None:
        rows = self._query("SELECT definition FROM workflows WHERE id = ?", (workflow_id,))
        return WorkflowDefinition.model_validate_json(rows[0]["definition"]) if rows else None

    def list_workflows(self) -> list[dict[str, Any]]:
        rows = self._query(
            "SELECT id, name, description, active, created_at, updated_at FROM workflows ORDER BY updated_at DESC"
        )
        return [dict(r) | {"active": bool(r["active"])} for r in rows]

    def set_workflow_active(self, workflow_id: str, active: bool) -> bool:
        with self._tx() as c:
            return c.execute(
                "UPDATE workflows SET active = ? WHERE id = ?", (int(active), workflow_id)
            ).rowcount > 0

    def active_workflows(self) -> list[tuple[WorkflowDefinition, str]]:
        """``(workflow, updated_at)`` pairs, the input ``TriggerManager.sync`` expects."""
        rows = self._query("SELECT definition, updated_at FROM workflows WHERE active = 1")
        return [(WorkflowDefinition.model_validate_json(r["definition"]), r["updated_at"]) for r in rows]

    def delete_workflow(self, workflow_id: str, *, with_history: bool = True) -> bool:
        with self._tx() as c:
            deleted = c.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,)).rowcount
            if with_history:
                c.execute("DELETE FROM executions WHERE workflow_id = ?", (workflow_id,))
        return deleted > 0

    # ------------------------------------------------------------------ executions

    def save_execution(self, result: ExecutionResult) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT OR REPLACE INTO executions
                   (id, workflow_id, workflow_name, status, error, started_at, finished_at, result)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (result.execution_id, result.workflow_id, result.workflow_name, result.status.value,
                 result.error, result.started_at.isoformat(),
                 result.finished_at.isoformat() if result.finished_at else None,
                 result.model_dump_json()),
            )

    def get_execution(self, execution_id: str) -> ExecutionResult | None:
        rows = self._query("SELECT result FROM executions WHERE id = ?", (execution_id,))
        return ExecutionResult.model_validate_json(rows[0]["result"]) if rows else None

    def list_executions(self, workflow_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        sql = "SELECT id, workflow_id, workflow_name, status, error, started_at, finished_at FROM executions"
        args: tuple = ()
        if workflow_id:
            sql += " WHERE workflow_id = ?"
            args = (workflow_id,)
        rows = self._query(sql + " ORDER BY started_at DESC LIMIT ?", (*args, limit))
        return [dict(r) for r in rows]

    def prune_executions(self, keep_per_workflow: int = 200) -> int:
        with self._tx() as c:
            return c.execute(
                """DELETE FROM executions WHERE id IN (
                     SELECT id FROM (
                       SELECT id, ROW_NUMBER() OVER (PARTITION BY workflow_id ORDER BY started_at DESC) AS rn
                       FROM executions) WHERE rn > ?)""",
                (keep_per_workflow,),
            ).rowcount

    # ------------------------------------------------------------------ settings (non-secret)

    def get_setting(self, key: str, default: Any = None) -> Any:
        rows = self._query("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_setting(self, key: str, value: Any) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, json.dumps(value), utcnow().isoformat()),
            )

    # ------------------------------------------------------------------ credentials

    def set_credential(self, name: str, data: dict[str, Any], type: str = "generic") -> None:
        if not name.strip():
            raise ValueError("credential name is required")
        now = utcnow().isoformat()
        with self._tx() as c:
            c.execute(
                """INSERT INTO credentials (name, type, data, fields, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET type=excluded.type, data=excluded.data,
                       fields=excluded.fields, updated_at=excluded.updated_at""",
                (name, type, self._vault.encrypt(data), json.dumps(sorted(data)), now, now),
            )

    def get_credential_sync(self, name: str) -> dict[str, Any]:
        rows = self._query("SELECT data FROM credentials WHERE name = ?", (name,))
        if not rows:
            raise CredentialNotFoundError(f"credential '{name}' does not exist")
        return self._vault.decrypt(rows[0]["data"])

    async def get_credential(self, name: str) -> dict[str, Any]:
        """``CredentialProvider`` implementation for the engine."""
        return await asyncio.to_thread(self.get_credential_sync, name)

    def list_credentials(self) -> list[dict[str, Any]]:
        """Names, types and field names only. Never returns secret values."""
        rows = self._query("SELECT name, type, fields, created_at, updated_at FROM credentials ORDER BY name")
        return [dict(r) | {"fields": json.loads(r["fields"])} for r in rows]

    def delete_credential(self, name: str) -> bool:
        with self._tx() as c:
            return c.execute("DELETE FROM credentials WHERE name = ?", (name,)).rowcount > 0
