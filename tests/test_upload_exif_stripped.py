"""PLAN decision 7: a worker phone's EXIF/GPS does not survive the save.

The row's path under data/images and the bytes /api/me/jobs/{id}/image hands
back are the same file, so one assertion on the path and one on the route cover
the whole KVKK surface.
"""
import io
import pathlib
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import auth, db
from app.main import create_app

EXIF_SEGMENT = b"Exif\x00\x00"
ORIENTATION = 0x0112
GPS_IFD = 0x8825
BROKEN = b"\xff\xd8\xff\xe0fakejpeg"


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


def phone_photo(width: int = 400, height: int = 200) -> bytes:
    """A shot straight from a phone: orientation 6, GPS, black top-left corner."""
    img = Image.new("RGB", (width, height), "white")
    img.paste("black", (0, 0, width // 20, height // 10))
    exif = Image.Exif()
    exif[ORIENTATION] = 6
    gps = exif.get_ifd(GPS_IFD)
    gps[1] = "N"
    gps[2] = [Fraction(39), Fraction(54), Fraction(0)]
    gps[3] = "E"
    gps[4] = [Fraction(32), Fraction(51), Fraction(0)]
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes(), quality=95)
    return buf.getvalue()


def clean_photo(width: int = 400, height: int = 200) -> bytes:
    """What the crop sheet uploads: upright pixels, no metadata at all."""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, "JPEG", quality=95)
    return buf.getvalue()


def submit(client, plaintext, image):
    return client.post(
        "/v1/jobs",
        headers={"X-API-Key": plaintext},
        files={"image": ("fis.jpg", image, "image/jpeg")},
    )


def stored(conn, job_id) -> pathlib.Path:
    return pathlib.Path(db.get_job(conn, job_id)["image_path"])


def test_the_phone_photo_actually_carries_exif_and_gps():
    exif = Image.open(io.BytesIO(phone_photo())).getexif()
    assert exif[ORIENTATION] == 6
    assert exif.get_ifd(GPS_IFD)[1] == "N"


def test_phone_exif_is_stripped_from_the_stored_file(env):
    _, client, conn, _, plaintext = env
    job_id = submit(client, plaintext, phone_photo()).json()["job_id"]
    path = stored(conn, job_id)
    assert EXIF_SEGMENT not in path.read_bytes()
    assert not dict(Image.open(path).getexif())


def test_phone_gps_is_stripped_from_the_stored_file(env):
    _, client, conn, _, plaintext = env
    job_id = submit(client, plaintext, phone_photo()).json()["job_id"]
    assert not dict(Image.open(stored(conn, job_id)).getexif().get_ifd(GPS_IFD))


def test_orientation_is_baked_into_the_stored_pixels(env):
    _, client, conn, _, plaintext = env
    job_id = submit(client, plaintext, phone_photo()).json()["job_id"]
    img = Image.open(stored(conn, job_id))
    assert img.size == (200, 400)
    assert sum(img.getpixel((5, 5))) > 600
    assert sum(img.getpixel((img.size[0] - 6, 5))) < 200


def test_the_served_image_carries_no_exif(env):
    _, client, _, _, plaintext = env
    job_id = submit(client, plaintext, phone_photo()).json()["job_id"]
    resp = client.get(f"/api/me/jobs/{job_id}/image", headers={"X-API-Key": plaintext})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert EXIF_SEGMENT not in resp.content
    assert not dict(Image.open(io.BytesIO(resp.content)).getexif())


def test_a_clean_upload_is_stored_verbatim(env):
    _, client, conn, _, plaintext = env
    raw = clean_photo()
    job_id = submit(client, plaintext, raw).json()["job_id"]
    assert stored(conn, job_id).read_bytes() == raw


def test_an_undecodable_upload_is_still_accepted(env):
    _, client, conn, _, plaintext = env
    resp = submit(client, plaintext, BROKEN)
    assert resp.status_code == 202
    assert stored(conn, resp.json()["job_id"]).read_bytes() == BROKEN
