"""T46 hardening: intake refuses junk, responses stay clean, requests are traceable.

Every check goes through the real app, so the middleware order that ships is
the one under test — upload cap, then security headers, then the request log,
all three outside auth.
"""
import io
import logging
import os
import pathlib

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import auth, db
from app.main import create_app

BOUNDARY = "t46"
NOT_AN_IMAGE = b"\xff\xd8\xff\xe0fakejpeg"
MB = 1024 * 1024


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


def jpeg(width=600, height=400, noise=False) -> bytes:
    """A real decodable JPEG; noise=True makes it uncompressible and heavy."""
    if noise:
        img = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
    else:
        img = Image.new("RGB", (width, height), "white")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def phone_photo(width=200, height=400) -> bytes:
    """A shot straight from a phone: EXIF orientation 6 on the pixels."""
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(
        buf, "JPEG", exif=exif.tobytes(), quality=95
    )
    return buf.getvalue()


def submit(client, plaintext, image):
    return client.post(
        "/v1/jobs",
        headers=headers(plaintext),
        files={"image": ("fis.jpg", image, "image/jpeg")},
    )


def multipart(image: bytes) -> bytes:
    """Hand-built body, so it can travel chunked and carry no Content-Length."""
    head = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="image"; filename="fis.jpg"\r\n'
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode()
    return head + image + f"\r\n--{BOUNDARY}--\r\n".encode()


def logged(caplog) -> list[str]:
    return [rec.getMessage() for rec in caplog.records if rec.name == "app.request"]


# --- max upload size ---


def test_an_oversize_upload_is_413_with_turkish_copy(env, monkeypatch):
    _, client, conn, _, plaintext = env
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    blob = jpeg(1400, 1000, noise=True)
    assert len(blob) > MB  # the cap, not the content, is what refuses this
    resp = submit(client, plaintext, blob)
    assert resp.status_code == 413
    body = resp.json()["error"]
    assert body["code"] == "payload_too_large"
    assert "1 MB sınırını aşıyor" in body["message"]
    assert "kırp" in body["message"]
    assert db.list_jobs(conn) == []


def test_a_chunked_upload_without_a_content_length_hits_the_same_cap(
    env, monkeypatch
):
    _, client, conn, _, plaintext = env
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    blob = jpeg(1400, 1000, noise=True)
    resp = client.post(
        "/v1/jobs",
        headers={
            **headers(plaintext),
            "Content-Type": f"multipart/form-data; boundary={BOUNDARY}",
        },
        content=iter([multipart(blob)]),
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"
    assert db.list_jobs(conn) == []


def test_a_phone_sized_upload_still_passes_the_cap(env):
    _, client, conn, _, plaintext = env
    assert submit(client, plaintext, jpeg(1600, 1200, noise=True)).status_code == 202
    assert len(db.list_jobs(conn)) == 1


# --- the upload has to be a real image ---


@pytest.mark.parametrize(
    "blob",
    [NOT_AN_IMAGE, b"merhaba dunya", b"%PDF-1.4\n%ben jpeg degilim"],
    ids=["jpeg-magic-only", "plain-text", "pdf-header"],
)
def test_a_file_that_is_not_an_image_is_422(env, blob):
    _, client, conn, _, plaintext = env
    resp = submit(client, plaintext, blob)
    assert resp.status_code == 422
    body = resp.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"][0]["field"] == "body.image"
    assert "görsel" in body["details"][0]["message"]
    assert db.list_jobs(conn) == []


def test_a_truncated_jpeg_is_refused_though_its_header_decodes(env):
    _, client, conn, _, plaintext = env
    blob = jpeg(900, 700, noise=True)
    resp = submit(client, plaintext, blob[: len(blob) // 3])
    assert resp.status_code == 422
    assert "görsel" in resp.json()["error"]["details"][0]["message"]
    assert db.list_jobs(conn) == []


def test_a_phone_photo_is_stored_without_exif_and_upright(env):
    _, client, conn, _, plaintext = env
    job_id = submit(client, plaintext, phone_photo()).json()["job_id"]
    path = pathlib.Path(db.get_job(conn, job_id)["image_path"])
    assert b"Exif\x00\x00" not in path.read_bytes()
    assert Image.open(path).size == (400, 200)


# --- security headers ---


def test_every_response_carries_the_security_headers(env):
    _, client, _, _, plaintext = env
    responses = [
        client.get("/health"),
        client.get("/app/"),
        client.get("/v1/jobs", headers=headers(plaintext)),
        client.get("/v1/jobs"),  # an auth rejection is a response too
    ]
    for resp in responses:
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "no-referrer"
        csp = resp.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp


def test_docs_keeps_loading_its_cdn_swagger(env):
    _, client, *_ = env
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "Content-Security-Policy" not in resp.headers


# --- no stack traces on the wire ---


def test_a_crash_leaves_the_envelope_on_the_wire_and_the_trace_in_the_log(env, caplog):
    app, client, _, _, plaintext = env

    @app.get("/v1/boom")
    def boom():
        raise RuntimeError("şirket içi bağlantı: postgres://gizli")

    with caplog.at_level(logging.ERROR):
        resp = client.get("/v1/boom", headers=headers(plaintext))
    assert resp.status_code == 500
    assert resp.json() == {
        "error": {"code": "internal_error", "message": "unexpected server error"}
    }
    assert "Traceback" not in resp.text
    assert "gizli" not in resp.text
    crashes = [rec for rec in caplog.records if rec.levelname == "ERROR"]
    assert crashes and crashes[0].exc_info[0] is RuntimeError
    assert "/v1/boom" in crashes[0].getMessage()


# --- request logging with job ids ---


def test_uploads_and_polls_are_logged_with_their_job_id(env, caplog):
    _, client, _, _, plaintext = env
    with caplog.at_level(logging.INFO, logger="app.request"):
        job_id = submit(client, plaintext, jpeg()).json()["job_id"]
        client.get(f"/v1/jobs/{job_id}", headers=headers(plaintext))
    lines = logged(caplog)
    assert any(f"POST /v1/jobs 202 " in line and f"job={job_id}" in line for line in lines)
    assert any(
        f"GET /v1/jobs/{job_id} 200 " in line and f"job={job_id}" in line
        for line in lines
    )
    assert all("worker=ayse" in line for line in lines)


def test_serving_a_stored_image_logs_the_job_it_belongs_to(env, caplog):
    _, client, _, _, plaintext = env
    job_id = submit(client, plaintext, jpeg()).json()["job_id"]
    with caplog.at_level(logging.INFO, logger="app.request"):
        resp = client.get(f"/api/me/jobs/{job_id}/image", headers=headers(plaintext))
    assert resp.status_code == 200
    assert any(f"job={job_id}" in line for line in logged(caplog))


def test_a_rejected_request_is_logged_too(env, caplog):
    _, client, *_ = env
    with caplog.at_level(logging.INFO, logger="app.request"):
        assert client.get("/v1/jobs").status_code == 401
    assert any(
        line.startswith("GET /v1/jobs 401 ") and "job=- worker=-" in line
        for line in logged(caplog)
    )
