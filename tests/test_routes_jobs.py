import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import auth, db
from app.main import create_app

ENVELOPE_KEYS = {"job_id", "status", "client_ref", "result", "validation", "meta"}


def jpeg(width: int = 60, height: int = 40) -> bytes:
    """A real decodable JPEG; T46's _require_image refuses anything else."""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, "JPEG", quality=90)
    return buf.getvalue()


IMAGE = jpeg()


@pytest.fixture
def env(tmp_path, monkeypatch):
    auth._buckets.clear()
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    key_id, plaintext = auth.create_key(conn, "ayse")
    app = create_app(db_path=path)
    client = TestClient(app, raise_server_exceptions=False)
    yield app, client, conn, key_id, plaintext
    conn.close()
    auth._buckets.clear()


def headers(plaintext):
    return {"X-API-Key": plaintext}


def submit(client, plaintext, data=None, image=IMAGE):
    return client.post(
        "/v1/jobs",
        headers=headers(plaintext),
        files={"image": ("fis.jpg", image, "image/jpeg")},
        data=data or {},
    )


def iso(offset_minutes: int) -> str:
    stamp = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    return stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --- POST /v1/jobs ---


def test_post_returns_202_with_queued_envelope(env):
    _, client, conn, key_id, plaintext = env
    resp = submit(client, plaintext, {"client_ref": "fis-001"})
    assert resp.status_code == 202
    body = resp.json()
    assert set(body) == ENVELOPE_KEYS
    assert body["status"] == "queued"
    assert body["client_ref"] == "fis-001"
    assert body["result"] is None
    assert body["validation"] is None
    assert body["meta"]["worker"] == "ayse"
    assert body["meta"]["received_at"]
    row = db.get_job(conn, body["job_id"])
    assert row["key_id"] == key_id
    assert row["worker"] == "ayse"


def test_post_stores_the_image_for_the_worker(env):
    _, client, conn, _, plaintext = env
    job_id = submit(client, plaintext).json()["job_id"]
    image_path = db.get_job(conn, job_id)["image_path"]
    # The stored file is the EXIF-stripped re-encode, so compare what the OCR
    # stage sees (decoded pixels), not the bytes on disk.
    with Image.open(io.BytesIO(IMAGE)) as sent, Image.open(image_path) as stored:
        assert stored.format == "JPEG"
        assert stored.size == sent.size
        assert stored.convert("RGB").tobytes() == sent.convert("RGB").tobytes()


def test_post_defaults_to_fast_mode(env):
    _, client, conn, _, plaintext = env
    job_id = submit(client, plaintext).json()["job_id"]
    assert db.get_job(conn, job_id)["mode"] == "fast"


def test_post_accepts_quality_mode(env):
    _, client, conn, _, plaintext = env
    job_id = submit(client, plaintext, {"mode": "quality"}).json()["job_id"]
    assert db.get_job(conn, job_id)["mode"] == "quality"


def test_unknown_mode_is_422_envelope(env):
    _, client, _, _, plaintext = env
    resp = submit(client, plaintext, {"mode": "turbo"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_missing_image_is_422(env):
    _, client, _, _, plaintext = env
    resp = client.post("/v1/jobs", headers=headers(plaintext), data={})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_empty_image_is_422(env):
    _, client, _, _, plaintext = env
    resp = submit(client, plaintext, image=b"")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


# --- idempotency on client_ref ---


def test_duplicate_client_ref_is_200_with_the_same_job(env):
    _, client, conn, _, plaintext = env
    first = submit(client, plaintext, {"client_ref": "fis-001"})
    second = submit(client, plaintext, {"client_ref": "fis-001"})
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["job_id"] == first.json()["job_id"]
    assert len(db.list_jobs(conn)) == 1


def test_duplicate_does_not_requeue_a_finished_job(env):
    _, client, conn, _, plaintext = env
    job_id = submit(client, plaintext, {"client_ref": "fis-001"}).json()["job_id"]
    db.set_status(conn, job_id, "running")
    db.set_status(conn, job_id, "done", result_json={"items": []})
    resp = submit(client, plaintext, {"client_ref": "fis-001"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"
    assert db.get_job(conn, job_id)["status"] == "done"


def test_absent_client_ref_never_collides(env):
    _, client, _, _, plaintext = env
    first = submit(client, plaintext).json()["job_id"]
    second = submit(client, plaintext).json()["job_id"]
    assert first != second


def test_same_client_ref_under_another_key_is_a_new_job(env):
    _, client, conn, _, plaintext = env
    _, other_key = auth.create_key(conn, "mehmet")
    first = submit(client, plaintext, {"client_ref": "fis-001"})
    second = submit(client, other_key, {"client_ref": "fis-001"})
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["job_id"] != second.json()["job_id"]


# --- captured_at ---


def test_captured_at_lands_in_meta(env):
    _, client, conn, _, plaintext = env
    stamp = "2026-10-30T14:03:00Z"
    body = submit(client, plaintext, {"captured_at": stamp}).json()
    assert body["meta"]["captured_at"] == stamp
    stored = json.loads(db.get_job(conn, body["job_id"])["meta_json"])
    assert stored["captured_at"] == stamp


def test_invalid_captured_at_is_422(env):
    _, client, _, _, plaintext = env
    resp = submit(client, plaintext, {"captured_at": "30/10/2026 14:03"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


# --- GET /v1/jobs/{id} ---


def test_get_job_returns_the_matured_envelope(env):
    _, client, conn, _, plaintext = env
    job_id = submit(client, plaintext, {"client_ref": "fis-001"}).json()["job_id"]
    db.set_status(conn, job_id, "running")
    db.set_status(
        conn,
        job_id,
        "done",
        result_json={
            "items": [{"ad": "Çay", "miktar": 1.0, "birim_fiyat": 12.5, "toplam": 12.5}],
            "totals": {"ara_toplam": 12.5, "kdv": 2.08, "toplam": 12.5},
        },
        validation_json={"verdict": "ok", "fields": []},
        meta_json={
            "model": "strata",
            "ocr_ms": 1234,
            "total_ms": 2222,
            "received_at": "2026-10-31T09:00:00.000Z",
        },
    )
    resp = client.get(f"/v1/jobs/{job_id}", headers=headers(plaintext))
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == ENVELOPE_KEYS
    assert body["status"] == "done"
    assert body["client_ref"] == "fis-001"
    assert body["result"]["items"][0]["ad"] == "Çay"
    assert body["result"]["totals"]["toplam"] == 12.5
    assert body["validation"]["verdict"] == "ok"
    assert body["meta"]["model"] == "strata"
    assert body["meta"]["ocr_ms"] == 1234
    assert body["meta"]["worker"] == "ayse"
    assert body["meta"]["received_at"] == "2026-10-31T09:00:00.000Z"


def test_get_unknown_job_is_404_envelope(env):
    _, client, _, _, plaintext = env
    resp = client.get(
        "/v1/jobs/00000000-0000-0000-0000-000000000000", headers=headers(plaintext)
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# --- GET /v1/jobs ---


def test_list_returns_envelopes(env):
    _, client, _, _, plaintext = env
    ids = {submit(client, plaintext).json()["job_id"] for _ in range(3)}
    resp = client.get("/v1/jobs", headers=headers(plaintext))
    assert resp.status_code == 200
    bodies = resp.json()
    assert {body["job_id"] for body in bodies} == ids
    assert all(set(body) == ENVELOPE_KEYS for body in bodies)


def test_list_filters_by_status(env):
    _, client, conn, _, plaintext = env
    done_id = submit(client, plaintext).json()["job_id"]
    submit(client, plaintext)
    db.set_status(conn, done_id, "running")
    db.set_status(conn, done_id, "done")
    bodies = client.get("/v1/jobs?status=done", headers=headers(plaintext)).json()
    assert [body["job_id"] for body in bodies] == [done_id]


def test_list_filters_by_worker(env):
    _, client, conn, _, plaintext = env
    mine = submit(client, plaintext).json()["job_id"]
    _, other_key = auth.create_key(conn, "mehmet")
    submit(client, other_key)
    bodies = client.get("/v1/jobs?worker=ayse", headers=headers(plaintext)).json()
    assert [body["job_id"] for body in bodies] == [mine]


def test_list_filters_by_since(env):
    _, client, _, _, plaintext = env
    submit(client, plaintext)
    bodies = client.get(f"/v1/jobs?since={iso(-5)}", headers=headers(plaintext)).json()
    assert len(bodies) == 1
    bodies = client.get(f"/v1/jobs?since={iso(5)}", headers=headers(plaintext)).json()
    assert bodies == []


def test_invalid_since_is_422(env):
    _, client, _, _, plaintext = env
    resp = client.get("/v1/jobs?since=dün", headers=headers(plaintext))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_mine_limits_to_the_callers_key(env):
    _, client, conn, _, plaintext = env
    mine = submit(client, plaintext).json()["job_id"]
    _, other_key = auth.create_key(conn, "mehmet")
    submit(client, other_key)
    bodies = client.get("/v1/jobs?mine=true", headers=headers(plaintext)).json()
    assert [body["job_id"] for body in bodies] == [mine]
    assert len(client.get("/v1/jobs", headers=headers(plaintext)).json()) == 2


def test_invalid_status_filter_is_422(env):
    _, client, _, _, plaintext = env
    resp = client.get("/v1/jobs?status=bogus", headers=headers(plaintext))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
