import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import auth, config, db
from app.main import create_app

LITE_KEYS = {
    "job_id",
    "status",
    "client_ref",
    "received_at",
    "thumbnail_url",
    "verdict",
    "toplam",
}
ENVELOPE_KEYS = {"job_id", "status", "client_ref", "result", "validation", "meta"}


def jpeg(width: int = 800, height: int = 600) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, "JPEG", quality=95)
    return buf.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    auth._buckets.clear()
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    key_id, plaintext = auth.create_key(conn, "ayse")
    other_id, other_key = auth.create_key(conn, "mehmet")
    app = create_app(db_path=path)
    client = TestClient(app, raise_server_exceptions=False)
    yield app, client, conn, key_id, plaintext, other_id, other_key
    conn.close()
    auth._buckets.clear()


def headers(plaintext):
    return {"X-API-Key": plaintext}


def submit(client, plaintext, image=None, data=None):
    return client.post(
        "/v1/jobs",
        headers=headers(plaintext),
        files={"image": ("fis.jpg", image or jpeg(), "image/jpeg")},
        data=data or {},
    )


def finish(conn, job_id, verdict="ok", toplam=148.0):
    db.set_status(conn, job_id, "running")
    db.set_status(
        conn,
        job_id,
        "done",
        result_json={
            "items": [{"ad": "Süt", "miktar": 2.0, "birim_fiyat": 74.0, "toplam": 148.0}],
            "totals": {"ara_toplam": 148.0, "iskonto": 0.0, "kdv": 26.72, "toplam": toplam},
        },
        validation_json={"verdict": verdict, "fields": [] if verdict == "ok" else ["totals.kdv"]},
    )


# --- GET /api/me/jobs ---


def test_list_returns_lite_rows_scoped_to_the_key(env):
    _, client, conn, _, plaintext, _, other_key = env
    mine = {submit(client, plaintext, data={"client_ref": f"f-{i}"}).json()["job_id"] for i in range(2)}
    submit(client, other_key)
    resp = client.get("/api/me/jobs", headers=headers(plaintext))
    assert resp.status_code == 200
    body = resp.json()
    assert {job["job_id"] for job in body["jobs"]} == mine
    assert all(set(job) == LITE_KEYS for job in body["jobs"])
    assert body["total"] == 2


def test_list_total_counts_every_job_of_the_key(env):
    _, client, _, _, plaintext, _, _ = env
    for i in range(3):
        submit(client, plaintext)
    body = client.get("/api/me/jobs", headers=headers(plaintext)).json()
    assert body["total"] == 3
    assert len(body["jobs"]) == 3


def test_queued_job_has_no_verdict_or_toplam_yet(env):
    _, client, _, _, plaintext, _, _ = env
    job_id = submit(client, plaintext, data={"client_ref": "f-1"}).json()["job_id"]
    job = client.get("/api/me/jobs", headers=headers(plaintext)).json()["jobs"][0]
    assert job["job_id"] == job_id
    assert job["status"] == "queued"
    assert job["client_ref"] == "f-1"
    assert job["received_at"]
    assert job["thumbnail_url"] == f"/api/me/jobs/{job_id}/thumbnail"
    assert job["verdict"] is None
    assert job["toplam"] is None


def test_done_job_shows_verdict_and_toplam(env):
    _, client, conn, _, plaintext, _, _ = env
    job_id = submit(client, plaintext).json()["job_id"]
    finish(conn, job_id, verdict="mismatch", toplam=137.5)
    job = client.get("/api/me/jobs", headers=headers(plaintext)).json()["jobs"][0]
    assert job["status"] == "done"
    assert job["verdict"] == "mismatch"
    assert job["toplam"] == 137.5


def test_list_handles_a_done_job_without_totals(env):
    _, client, conn, _, plaintext, _, _ = env
    job_id = submit(client, plaintext).json()["job_id"]
    db.set_status(conn, job_id, "running")
    db.set_status(conn, job_id, "done", result_json={"items": []})
    job = client.get("/api/me/jobs", headers=headers(plaintext)).json()["jobs"][0]
    assert job["verdict"] is None
    assert job["toplam"] is None


def test_job_without_an_image_has_no_thumbnail_url(env):
    _, client, conn, key_id, plaintext, _, _ = env
    db.create_job(conn, key_id=key_id, worker="ayse")
    body = client.get("/api/me/jobs", headers=headers(plaintext)).json()
    assert body["jobs"][0]["thumbnail_url"] is None


# --- GET /api/me/jobs/{id} ---


def test_detail_returns_the_envelope_plus_image_url(env):
    _, client, conn, _, plaintext, _, _ = env
    job_id = submit(client, plaintext, data={"client_ref": "f-1"}).json()["job_id"]
    finish(conn, job_id)
    resp = client.get(f"/api/me/jobs/{job_id}", headers=headers(plaintext))
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == ENVELOPE_KEYS | {"image_url"}
    assert body["job_id"] == job_id
    assert body["status"] == "done"
    assert body["client_ref"] == "f-1"
    assert body["result"]["totals"]["toplam"] == 148.0
    assert body["validation"]["verdict"] == "ok"
    assert body["meta"]["worker"] == "ayse"
    assert body["image_url"] == f"/api/me/jobs/{job_id}/image"


def test_detail_of_another_workers_job_is_404(env):
    _, client, _, _, plaintext, _, other_key = env
    job_id = submit(client, other_key).json()["job_id"]
    resp = client.get(f"/api/me/jobs/{job_id}", headers=headers(plaintext))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_detail_of_unknown_job_is_404(env):
    _, client, _, _, plaintext, _, _ = env
    resp = client.get(
        "/api/me/jobs/00000000-0000-0000-0000-000000000000", headers=headers(plaintext)
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_detail_without_an_image_has_null_image_url(env):
    _, client, conn, key_id, plaintext, _, _ = env
    job = db.create_job(conn, key_id=key_id, worker="ayse")
    resp = client.get(f"/api/me/jobs/{job['id']}", headers=headers(plaintext))
    assert resp.status_code == 200
    assert resp.json()["image_url"] is None


# --- thumbnail ---


def test_thumbnail_is_resized_to_the_configured_edge(env):
    _, client, _, _, plaintext, _, _ = env
    job_id = submit(client, plaintext).json()["job_id"]
    resp = client.get(f"/api/me/jobs/{job_id}/thumbnail", headers=headers(plaintext))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(resp.content))
    assert max(img.size) <= config.thumb_max_edge()


def test_thumbnail_is_cached_and_stable(env):
    _, client, _, _, plaintext, _, _ = env
    job_id = submit(client, plaintext).json()["job_id"]
    url = f"/api/me/jobs/{job_id}/thumbnail"
    first = client.get(url, headers=headers(plaintext)).content
    second = client.get(url, headers=headers(plaintext)).content
    assert first == second
    assert (config.data_dir() / "thumbs" / f"{job_id}.jpg").is_file()


def test_undecodable_image_still_serves_its_bytes(env):
    _, client, conn, key_id, plaintext, _, _ = env
    raw = b"\xff\xd8\xff\xe0fakejpeg"
    path = config.images_dir() / "broken.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    job = db.create_job(conn, key_id=key_id, worker="ayse", image_path=str(path))
    resp = client.get(f"/api/me/jobs/{job['id']}/thumbnail", headers=headers(plaintext))
    assert resp.status_code == 200
    assert resp.content == raw


def test_thumbnail_of_another_workers_job_is_404(env):
    _, client, _, _, plaintext, _, other_key = env
    job_id = submit(client, other_key).json()["job_id"]
    resp = client.get(f"/api/me/jobs/{job_id}/thumbnail", headers=headers(plaintext))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_thumbnail_of_a_missing_file_is_404(env):
    _, client, conn, key_id, plaintext, _, _ = env
    job = db.create_job(
        conn, key_id=key_id, worker="ayse", image_path=str(config.images_dir() / "gone.jpg")
    )
    resp = client.get(f"/api/me/jobs/{job['id']}/thumbnail", headers=headers(plaintext))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# --- image ---


def test_image_returns_the_original_bytes(env):
    _, client, _, _, plaintext, _, _ = env
    raw = jpeg(640, 480)
    job_id = submit(client, plaintext, image=raw).json()["job_id"]
    resp = client.get(f"/api/me/jobs/{job_id}/image", headers=headers(plaintext))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content == raw


def test_image_of_another_workers_job_is_404(env):
    _, client, _, _, plaintext, _, other_key = env
    job_id = submit(client, other_key).json()["job_id"]
    resp = client.get(f"/api/me/jobs/{job_id}/image", headers=headers(plaintext))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# --- auth ---


def test_worker_api_requires_an_api_key(env):
    _, client, _, _, _, _, _ = env
    resp = client.get("/api/me/jobs")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_revoked_key_is_locked_out(env):
    _, client, conn, key_id, plaintext, _, _ = env
    auth.revoke_key(conn, key_id)
    resp = client.get("/api/me/jobs", headers=headers(plaintext))
    assert resp.status_code == 401
