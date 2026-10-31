"""T67: a queued row is never without its image.

The worker claims rows by status, so the intake order is the whole contract:
bytes on disk first, then a row that already points at them. Anything else
opens a window where a good receipt is claimed and failed with "image: …", or
where a failure on the way to the file leaves a queued row nobody can serve.
"""
import io
import os

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import auth, config, db, routes_jobs
from app.main import create_app


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


def photo() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 200), (200, 30, 30)).save(buf, "JPEG", quality=95)
    return buf.getvalue()


def submit(client, plaintext):
    return client.post(
        "/v1/jobs",
        headers={"X-API-Key": plaintext},
        files={"image": ("fis.jpg", photo(), "image/jpeg")},
    )


def test_a_strip_exif_failure_leaves_no_job_row(env, monkeypatch):
    """A decodable-but-odd upload must fail as if the POST never happened."""
    _, client, conn, _, plaintext = env

    def explode(data):
        raise RuntimeError("odd upload")

    monkeypatch.setattr(routes_jobs, "_strip_exif", explode)
    assert submit(client, plaintext).status_code == 500
    assert db.list_jobs(conn) == []
    images = config.images_dir()
    assert not images.exists() or list(images.iterdir()) == []


def test_the_row_lands_already_pointing_at_bytes_that_exist(env, monkeypatch):
    """At the instant the row is claimable, its file is already on disk."""
    _, client, conn, _, plaintext = env
    real = db.create_job
    seen = []

    def spy(*args, **kwargs):
        path = kwargs["image_path"]
        seen.append(bool(path) and os.path.exists(path))
        return real(*args, **kwargs)

    monkeypatch.setattr(db, "create_job", spy)
    job_id = submit(client, plaintext).json()["job_id"]
    assert seen == [True]
    row = db.get_job(conn, job_id)
    assert row["status"] == "queued"
    assert row["image_path"] == str(config.images_dir() / f"{job_id}.jpg")
