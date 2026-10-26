"""SQLite task, stage, asset, and approval records (PRD Phase 0)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from content_studio.models import ApprovalRecord, TaskStatus
from content_studio.utils import utc_now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    content_mode TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    input_sha256 TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS stage_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    usage_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error_class TEXT NOT NULL DEFAULT '',
    retry_count INTEGER NOT NULL DEFAULT 0,
    artifacts_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_stage_runs_task ON stage_runs(task_id, id);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(project_id, path)
);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    version TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    scope TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE(project_id, version)
);
"""


# Columns added after the first schema version. `CREATE TABLE IF NOT EXISTS`
# does not touch an existing database, so each is added explicitly when absent.
TASK_COLUMNS = {
    "run_id": "TEXT NOT NULL DEFAULT ''",
    "input_sha256": "TEXT NOT NULL DEFAULT ''",
    "config_json": "TEXT NOT NULL DEFAULT '{}'",
}
STAGE_COLUMNS = {
    "error_class": "TEXT NOT NULL DEFAULT ''",
    "retry_count": "INTEGER NOT NULL DEFAULT 0",
    "artifacts_json": "TEXT NOT NULL DEFAULT '[]'",
}


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, declaration in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


class TaskStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)
            _ensure_columns(conn, "tasks", TASK_COLUMNS)
            _ensure_columns(conn, "stage_runs", STAGE_COLUMNS)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # --- tasks ---------------------------------------------------------
    def create_task(
        self,
        project_id: str,
        content_mode: str,
        provider: str = "",
        model: str = "",
        *,
        run_id: str = "",
        input_sha256: str = "",
        config: dict[str, Any] | None = None,
    ) -> int:
        now = utc_now_iso()
        config_json = json.dumps(config or {}, ensure_ascii=False, sort_keys=True)
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO tasks (project_id, content_mode, provider, model, status, stage,"
                " created_at, updated_at, run_id, input_sha256, config_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    content_mode,
                    provider,
                    model,
                    "CREATED",
                    "",
                    now,
                    now,
                    run_id or uuid.uuid4().hex,
                    input_sha256,
                    config_json,
                ),
            )
            return int(cursor.lastrowid or 0)

    def update_task(
        self,
        task_id: int,
        *,
        status: TaskStatus | None = None,
        stage: str | None = None,
        error: str | None = None,
        input_sha256: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        sets: list[str] = ["updated_at = ?"]
        values: list[Any] = [utc_now_iso()]
        if status is not None:
            sets.append("status = ?")
            values.append(status)
        if stage is not None:
            sets.append("stage = ?")
            values.append(stage)
        if error is not None:
            sets.append("error = ?")
            values.append(error)
        if input_sha256 is not None:
            sets.append("input_sha256 = ?")
            values.append(input_sha256)
        if config is not None:
            sets.append("config_json = ?")
            values.append(json.dumps(config, ensure_ascii=False, sort_keys=True))
        values.append(task_id)
        with closing(self._connect()) as conn, conn:
            conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", values)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def latest_task(self, project_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY id DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_tasks(self, limit: int = 20, project_id: str | None = None) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE project_id = ? ORDER BY id DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(row) for row in rows]

    # --- stage runs ----------------------------------------------------
    def start_stage(
        self,
        task_id: int,
        stage: str,
        provider: str = "",
        model: str = "",
        *,
        retry_count: int = 0,
    ) -> int:
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO stage_runs (task_id, stage, status, provider, model, started_at,"
                " retry_count) VALUES (?, ?, 'running', ?, ?, ?, ?)",
                (task_id, stage, provider, model, utc_now_iso(), retry_count),
            )
            return int(cursor.lastrowid or 0)

    def finish_stage(
        self,
        run_id: int,
        *,
        status: str,
        usage: dict[str, int] | None = None,
        error: str = "",
        error_class: str = "",
        artifacts: list[str] | None = None,
    ) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE stage_runs SET status = ?, usage_json = ?, error = ?, finished_at = ?,"
                " error_class = ?, artifacts_json = ? WHERE id = ?",
                (
                    status,
                    json.dumps(usage or {}, ensure_ascii=False),
                    error,
                    utc_now_iso(),
                    error_class,
                    json.dumps(artifacts or [], ensure_ascii=False),
                    run_id,
                ),
            )

    def stage_runs(self, task_id: int) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM stage_runs WHERE task_id = ? ORDER BY id", (task_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def usage_rows(self, project_id: str | None = None) -> list[dict[str, Any]]:
        """Stage runs with their usage JSON, optionally for one project."""

        query = (
            "SELECT r.provider, r.model, r.status, r.usage_json,"
            " r.started_at, r.finished_at"
            " FROM stage_runs r JOIN tasks t ON t.id = r.task_id"
        )
        params: tuple[Any, ...] = ()
        if project_id:
            query += " WHERE t.project_id = ?"
            params = (project_id,)
        query += " ORDER BY r.id"
        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    # --- events --------------------------------------------------------
    def log_event(self, task_id: int | None, level: str, message: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO events (task_id, level, message, created_at) VALUES (?, ?, ?, ?)",
                (task_id, level, message, utc_now_iso()),
            )

    def events(self, task_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE task_id = ? ORDER BY id DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    # --- assets --------------------------------------------------------
    def register_asset(self, project_id: str, kind: str, path: str, sha256: str = "") -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO assets (project_id, kind, path, sha256, created_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(project_id, path) DO UPDATE SET kind = excluded.kind,"
                " sha256 = excluded.sha256, created_at = excluded.created_at",
                (project_id, kind, path, sha256, utc_now_iso()),
            )

    def assets(self, project_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM assets WHERE project_id = ? ORDER BY path", (project_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    # --- approvals -----------------------------------------------------
    def save_approval(self, record: ApprovalRecord) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO approvals (project_id, version, approved_by, approved_at,"
                " scope, notes) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(project_id, version) DO UPDATE SET"
                " approved_by = excluded.approved_by,"
                " approved_at = excluded.approved_at, scope = excluded.scope,"
                " notes = excluded.notes",
                (
                    record.project_id,
                    record.version,
                    record.approved_by,
                    record.approved_at.isoformat(),
                    record.scope,
                    record.notes,
                ),
            )

    def get_approval(self, project_id: str, version: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE project_id = ? AND version = ?",
                (project_id, version),
            ).fetchone()
        return dict(row) if row else None
