"""SQLite (WAL) storage: api_keys, jobs, corrections, events.

connect() is the only way in: it creates the file and its parent directories,
turns on WAL and foreign keys, and applies the migration list idempotently
(PRAGMA user_version), so every entry point can just open the database.
Job rows follow the queue-row contract in PLAN.md; status transitions stamp
created/started/finished as ISO-8601 UTC so every view sorts on one clock.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import uuid
from datetime import datetime, timezone

from app import config

STATUSES = ("queued", "running", "done", "failed")

# ASSUMPTION: mode is "fast" | "quality"; the contract names the column but
# not its vocabulary, and "fast" matches the non-quality default everywhere.
DEFAULT_MODE = "fast"

JOB_COLUMNS = frozenset(
    {
        "key_id",
        "worker",
        "client_ref",
        "status",
        "image_path",
        "mode",
        "result_json",
        "validation_json",
        "meta_json",
        "error",
        "created_at",
        "started_at",
        "finished_at",
    }
)
_JSON_FIELDS = frozenset({"result_json", "validation_json", "meta_json"})
# status changes only through set_status (timestamps); id/created_at never move
_IMMUTABLE = frozenset({"id", "created_at", "status"})

_MIGRATION_1 = """
CREATE TABLE api_keys (
    id         INTEGER PRIMARY KEY,
    key_hash   TEXT    NOT NULL UNIQUE,
    worker     TEXT    NOT NULL,
    revoked    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);

CREATE TABLE jobs (
    id              TEXT PRIMARY KEY,
    key_id          INTEGER REFERENCES api_keys(id),
    worker          TEXT NOT NULL DEFAULT '',
    client_ref      TEXT,
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'running', 'done', 'failed')),
    image_path      TEXT NOT NULL DEFAULT '',
    mode            TEXT NOT NULL DEFAULT 'fast',
    result_json     TEXT,
    validation_json TEXT,
    meta_json       TEXT,
    error           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    UNIQUE (key_id, client_ref)
);
CREATE INDEX jobs_status  ON jobs(status);
CREATE INDEX jobs_created ON jobs(created_at);

CREATE TABLE corrections (
    id         INTEGER PRIMARY KEY,
    job_id     TEXT    NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    field      TEXT    NOT NULL,
    old_value  TEXT    NOT NULL DEFAULT '',
    new_value  TEXT    NOT NULL DEFAULT '',
    who        TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL
);
CREATE INDEX corrections_job ON corrections(job_id);

CREATE TABLE events (
    id         INTEGER PRIMARY KEY,
    job_id     TEXT REFERENCES jobs(id) ON DELETE CASCADE,
    type       TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX events_job ON events(job_id);
"""

MIGRATIONS = (_MIGRATION_1,)


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open the database (default config.db_path()), WAL + migrated."""
    db = str(config.db_path() if path is None else path)
    in_memory = db == ":memory:"
    if not in_memory:
        pathlib.Path(db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if not in_memory:
        conn.execute("PRAGMA journal_mode = WAL")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for target, script in enumerate(MIGRATIONS, start=1):
        if version < target:
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version = {target}")
    conn.commit()


# --- api keys ---


def list_keys(conn: sqlite3.Connection) -> list[dict]:
    """Every key row, oldest first.

    key_hash is deliberately not selected: the admin panel shows identities,
    and a secret cannot leak from a column this function never reads.
    """
    rows = conn.execute(
        "SELECT id, worker, created_at, revoked FROM api_keys ORDER BY id"
    )
    return [dict(row) for row in rows]


# --- jobs ---


def create_job(
    conn: sqlite3.Connection,
    *,
    key_id: int | None = None,
    worker: str = "",
    client_ref: str | None = None,
    image_path: str = "",
    mode: str = DEFAULT_MODE,
) -> dict:
    """New queued job; created_at stamped, started/finished stay NULL."""
    job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, key_id, worker, client_ref, image_path, mode, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (job_id, key_id, worker, client_ref, image_path, mode, _now()),
    )
    conn.commit()
    return get_job(conn, job_id)


def get_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row is not None else None


def find_job_by_client_ref(
    conn: sqlite3.Connection, key_id: int | None, client_ref: str | None
) -> dict | None:
    """The idempotency lookup behind UNIQUE(key_id, client_ref); no ref, no match."""
    if not client_ref:
        return None
    row = conn.execute(
        "SELECT * FROM jobs WHERE key_id IS ? AND client_ref = ?",
        (key_id, client_ref),
    ).fetchone()
    return dict(row) if row is not None else None


def list_jobs(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    worker: str | None = None,
    key_id: int | None = None,
    since: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    where, args = [], []
    if status:
        where.append("status = ?")
        args.append(status)
    if worker:
        where.append("worker = ?")
        args.append(worker)
    if key_id is not None:
        where.append("key_id = ?")
        args.append(key_id)
    if since:
        where.append("created_at >= ?")
        args.append(since)
    sql = "SELECT * FROM jobs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, id LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    return [dict(row) for row in conn.execute(sql, args)]


def queue_depth(conn: sqlite3.Connection) -> dict:
    """Open queue depth per status; a status with no rows reads as 0."""
    sayilar = {
        satir["status"]: satir["adet"]
        for satir in conn.execute(
            "SELECT status, COUNT(*) AS adet FROM jobs GROUP BY status"
        )
    }
    return {durum: sayilar.get(durum, 0) for durum in ("queued", "running", "failed")}


def update_job(conn: sqlite3.Connection, job_id: str, **values) -> dict | None:
    """Update mutable job columns; dict/list JSON fields serialize.

    status is not settable here — use set_status so timestamps follow.
    """
    if get_job(conn, job_id) is None:
        return None
    _check_columns(values)
    _update(conn, job_id, values)
    return get_job(conn, job_id)


def set_status(
    conn: sqlite3.Connection, job_id: str, status: str, **updates
) -> dict | None:
    """queued -> running -> done/failed; done/failed -> queued for a rerun.

    running stamps started_at (first time only), done/failed stamp
    finished_at; extra job columns update in the same transaction.
    """
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status}")
    job = get_job(conn, job_id)
    if job is None:
        return None
    _check_columns(updates)
    sets = dict(updates)
    if status == "running" and not job["started_at"]:
        sets["started_at"] = _now()
    if status in ("done", "failed"):
        sets["finished_at"] = _now()
    sets["status"] = status
    _update(conn, job_id, sets)
    return get_job(conn, job_id)


def _check_columns(values: dict) -> None:
    for name in values:
        if name not in JOB_COLUMNS or name in _IMMUTABLE:
            raise ValueError(f"not a writable job column: {name}")


def _update(conn: sqlite3.Connection, job_id: str, sets: dict) -> None:
    parts, args = [], []
    for name, value in sets.items():
        if name in _JSON_FIELDS and isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        parts.append(f"{name} = ?")
        args.append(value)
    args.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(parts)} WHERE id = ?", args)
    conn.commit()


# --- corrections ---


def add_correction(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    field: str,
    old_value: str = "",
    new_value: str = "",
    who: str = "",
) -> dict:
    """One audit row for one corrected field, stamped with the time it landed."""
    cur = conn.execute(
        "INSERT INTO corrections (job_id, field, old_value, new_value, who, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (job_id, field, old_value, new_value, who, _now()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM corrections WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return dict(row)


# --- events ---


def log_event(
    conn: sqlite3.Connection, type_: str, job_id: str | None = None, detail: str = ""
) -> None:
    conn.execute(
        "INSERT INTO events (job_id, type, detail, created_at) VALUES (?, ?, ?, ?)",
        (job_id, type_, detail, _now()),
    )
    conn.commit()
