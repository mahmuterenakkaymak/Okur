import json
import re
import sqlite3
import uuid

import pytest

from app import config, db

QUEUE_ROW_KEYS = {
    "id",
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


@pytest.fixture
def conn(tmp_path):
    conn = db.connect(tmp_path / "ocr.db")
    yield conn
    conn.close()


def make_key(conn, worker):
    conn.execute(
        "INSERT INTO api_keys (key_hash, worker, created_at) VALUES (?, ?, ?)",
        (f"hash-{worker}", worker, "2026-10-31T00:00:00.000Z"),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM api_keys WHERE worker = ?", (worker,)
    ).fetchone()[0]


# --- connect / migrations ---


def test_connect_enables_wal_and_foreign_keys(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_connect_creates_missing_parent_dirs(tmp_path):
    path = tmp_path / "deep" / "nested" / "ocr.db"
    conn = db.connect(path)
    assert path.exists()
    conn.close()


def test_default_path_comes_from_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "from-config.db"))
    conn = db.connect()
    assert (tmp_path / "from-config.db").exists()
    assert config.db_path() == tmp_path / "from-config.db"
    conn.close()


def test_memory_database_works_without_wal():
    conn = db.connect(":memory:")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "memory"
    job = db.create_job(conn, worker="w")
    assert db.get_job(conn, job["id"])["worker"] == "w"


def test_schema_has_all_four_tables(conn):
    names = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"api_keys", "jobs", "corrections", "events"} <= names


def test_migrations_are_idempotent_across_reopens(tmp_path):
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    job = db.create_job(conn, worker="eren")
    conn.close()

    conn = db.connect(path)
    assert db.get_job(conn, job["id"])["worker"] == "eren"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    tables = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'jobs'"
    ).fetchone()[0]
    assert "client_ref" in tables
    conn.close()


# --- create / read ---


def test_create_job_defaults(conn):
    job = db.create_job(conn, worker="ayse")
    assert uuid.UUID(job["id"])
    assert job["status"] == "queued"
    assert job["worker"] == "ayse"
    assert job["mode"] == "fast"
    assert job["client_ref"] is None
    assert job["error"] == ""
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:]+\.\d{3}Z", job["created_at"])
    assert job["started_at"] is None
    assert job["finished_at"] is None


def test_job_row_matches_queue_contract(conn):
    job = db.create_job(conn, worker="ayse")
    assert set(job) == QUEUE_ROW_KEYS


def test_get_job_missing_returns_none(conn):
    assert db.get_job(conn, "nope") is None


def test_find_job_by_client_ref(conn):
    key = make_key(conn, "ayse")
    other = make_key(conn, "mehmet")
    job = db.create_job(conn, key_id=key, client_ref="ref-1")
    assert db.find_job_by_client_ref(conn, key, "ref-1")["id"] == job["id"]
    assert db.find_job_by_client_ref(conn, other, "ref-1") is None
    assert db.find_job_by_client_ref(conn, key, "other-ref") is None
    assert db.find_job_by_client_ref(conn, key, None) is None


def test_client_ref_unique_per_key_nulls_free(conn):
    key = make_key(conn, "ayse")
    other = make_key(conn, "mehmet")
    db.create_job(conn, key_id=key, client_ref="ref-1")
    with pytest.raises(sqlite3.IntegrityError):
        db.create_job(conn, key_id=key, client_ref="ref-1")
    db.create_job(conn, key_id=other, client_ref="ref-1")
    db.create_job(conn, key_id=key)
    db.create_job(conn, key_id=key)
    assert len(db.list_jobs(conn, key_id=key)) == 3


# --- update ---


def test_update_job_serializes_json_fields(conn):
    job = db.create_job(conn, worker="ayse")
    updated = db.update_job(
        conn, job["id"], result_json={"items": []}, meta_json={"ocr_ms": 12}, error="e"
    )
    assert json.loads(updated["result_json"]) == {"items": []}
    assert json.loads(updated["meta_json"]) == {"ocr_ms": 12}
    assert updated["error"] == "e"


def test_update_job_rejects_bad_columns(conn):
    job = db.create_job(conn)
    with pytest.raises(ValueError):
        db.update_job(conn, job["id"], nope=1)
    with pytest.raises(ValueError):
        db.update_job(conn, job["id"], status="done")
    with pytest.raises(ValueError):
        db.update_job(conn, job["id"], created_at="1999-01-01")
    assert db.update_job(conn, "missing", worker="x") is None


# --- status transitions ---


def test_transitions_stamp_timestamps(conn):
    job = db.create_job(conn, worker="ayse")
    running = db.set_status(conn, job["id"], "running")
    assert running["status"] == "running"
    assert running["started_at"] is not None
    assert running["finished_at"] is None

    done = db.set_status(conn, job["id"], "done")
    assert done["status"] == "done"
    assert done["created_at"] <= done["started_at"] <= done["finished_at"]


def test_started_at_survives_rerun(conn):
    job = db.create_job(conn)
    started = db.set_status(conn, job["id"], "running")["started_at"]
    db.set_status(conn, job["id"], "done")
    again = db.set_status(conn, job["id"], "queued")
    assert again["status"] == "queued"
    assert db.set_status(conn, job["id"], "running")["started_at"] == started


def test_set_status_carries_updates_in_one_call(conn):
    job = db.create_job(conn)
    db.set_status(
        conn,
        job["id"],
        "running",
        meta_json={"model": "strata"},
    )
    done = db.set_status(
        conn,
        job["id"],
        "done",
        result_json={"totals": {"toplam": 10.0}},
        validation_json={"verdict": "ok"},
    )
    assert json.loads(done["result_json"])["totals"]["toplam"] == 10.0
    assert json.loads(done["validation_json"])["verdict"] == "ok"
    assert json.loads(done["meta_json"])["model"] == "strata"


def test_failed_transition_stores_error(conn):
    job = db.create_job(conn)
    db.set_status(conn, job["id"], "running")
    failed = db.set_status(conn, job["id"], "failed", error="ocr timeout")
    assert failed["status"] == "failed"
    assert failed["error"] == "ocr timeout"
    assert failed["finished_at"] is not None


def test_set_status_rejects_unknown_status_and_missing_job(conn):
    job = db.create_job(conn)
    with pytest.raises(ValueError):
        db.set_status(conn, job["id"], "cancelled")
    assert db.set_status(conn, "missing", "running") is None


# --- listing ---


def test_list_jobs_filters_and_orders_newest_first(conn):
    a = db.create_job(conn, worker="ayse")
    b = db.create_job(conn, worker="ayse")
    c = db.create_job(conn, worker="mehmet")
    db.set_status(conn, c["id"], "done")
    conn.execute("UPDATE jobs SET created_at = ? WHERE id = ?", ("2026-01-01T00:00:00.000Z", a["id"]))
    conn.execute("UPDATE jobs SET created_at = ? WHERE id = ?", ("2026-06-01T00:00:00.000Z", b["id"]))
    conn.execute("UPDATE jobs SET created_at = ? WHERE id = ?", ("2026-09-01T00:00:00.000Z", c["id"]))
    conn.commit()

    assert [j["id"] for j in db.list_jobs(conn)] == [c["id"], b["id"], a["id"]]
    assert [j["id"] for j in db.list_jobs(conn, worker="ayse")] == [b["id"], a["id"]]
    assert [j["id"] for j in db.list_jobs(conn, status="done")] == [c["id"]]
    assert [j["id"] for j in db.list_jobs(conn, since="2026-06-01")] == [c["id"], b["id"]]
    assert [j["id"] for j in db.list_jobs(conn, limit=2)] == [c["id"], b["id"]]


# --- events / corrections tables ---


def test_log_event(conn):
    job = db.create_job(conn)
    db.log_event(conn, "job.created", job_id=job["id"], detail="queued by ayse")
    row = conn.execute("SELECT * FROM events").fetchone()
    assert row["type"] == "job.created"
    assert row["job_id"] == job["id"]
    assert row["detail"] == "queued by ayse"
    assert row["created_at"]


def test_corrections_row_roundtrip(conn):
    job = db.create_job(conn)
    conn.execute(
        "INSERT INTO corrections (job_id, field, old_value, new_value, who, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (job["id"], "items[0].toplam", "10,00", "12,50", "admin", "2026-10-31T00:00:00.000Z"),
    )
    row = conn.execute("SELECT field, new_value, who FROM corrections").fetchone()
    assert (row["field"], row["new_value"], row["who"]) == (
        "items[0].toplam",
        "12,50",
        "admin",
    )
