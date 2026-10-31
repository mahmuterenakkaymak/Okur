"""T27 — history view: page wiring, and only the caller key's jobs are reachable."""
import io
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import auth, db
from app.main import create_app

# every hook the history feed reaches for in index.html
HISTORY_HOOKS = (
    "gecmis",
    "gecmis-liste",
    "gecmis-bos",
    "gecmis-durum",
    "gecmis-sentinel",
    "gecmis-yenileme",
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    auth._buckets.clear()
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RATE_LIMIT_CAPACITY", "1000")
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    _, mine = auth.create_key(conn, "ayse")
    _, theirs = auth.create_key(conn, "mehmet")
    client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
    yield client, conn, mine, theirs
    conn.close()
    auth._buckets.clear()


def jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), (200, 30, 30)).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def submit(client, key) -> str:
    resp = client.post(
        "/v1/jobs",
        headers={"X-API-Key": key},
        files={"image": ("fis.jpg", jpeg(), "image/jpeg")},
    )
    return resp.json()["job_id"]


def headers(key):
    return {"X-API-Key": key}


# --- page wiring ---


def test_history_module_is_served(env):
    client, *_ = env
    resp = client.get("/app/history.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]


def test_app_wires_the_history_module(env):
    client, *_ = env
    src = client.get("/app/app.js").text
    assert 'from "./history.js"' in src
    assert "createHistory" in src


def test_history_reuses_the_api_client_and_status_labels(env):
    client, *_ = env
    src = client.get("/app/history.js").text
    assert 'from "./api.js"' in src and "listJobs" in src
    assert 'from "./status.js"' in src and "statusOf" in src


def test_page_defines_every_hook_history_reaches_for(env):
    client, *_ = env
    html = client.get("/app/").text
    src = client.get("/app/history.js").text + client.get("/app/app.js").text
    hooks = set(re.findall(r'getElementById\("([^"]+)"\)', src))
    assert set(HISTORY_HOOKS) <= hooks, "the feed hooks must all be reached"
    for hook in sorted(hooks):
        assert f'id="{hook}"' in html, f"index.html is missing #{hook}"


def test_empty_state_is_a_friendly_turkish_doodle(env):
    client, *_ = env
    html = client.get("/app/").text
    assert 'id="gecmis-bos" hidden' in html
    assert "Henüz fiş yok" in html
    doodle = html.split('id="gecmis-bos"', 1)[1].split("</div>", 1)[0]
    assert "<svg" in doodle  # hand-drawn receipt, no binary asset


def test_pull_to_refresh_and_infinite_scroll_are_wired(env):
    client, *_ = env
    src = client.get("/app/history.js").text
    for event in ("touchstart", "touchmove", "touchend"):
        assert event in src, event
    assert "IntersectionObserver" in src


def test_feed_shows_verdict_chips(env):
    client, *_ = env
    src = client.get("/app/history.js").text
    for chip in ("chip-on", "chip-off", "chip-bad"):
        assert chip in src, chip


# --- only the caller key's jobs are reachable ---


def test_list_contains_only_the_callers_jobs(env):
    client, _, mine, theirs = env
    mine_ids = {submit(client, mine) for _ in range(3)}
    their_ids = {submit(client, theirs) for _ in range(2)}
    body = client.get("/api/me/jobs", headers=headers(mine)).json()
    assert {job["job_id"] for job in body["jobs"]} == mine_ids
    assert body["total"] == 3
    assert not mine_ids & their_ids


def test_pages_walk_the_owners_feed_and_nothing_else(env):
    client, _, mine, theirs = env
    mine_ids = {submit(client, mine) for _ in range(5)}
    their_ids = {submit(client, theirs) for _ in range(2)}
    first = client.get("/api/me/jobs?limit=2&offset=0", headers=headers(mine)).json()
    second = client.get("/api/me/jobs?limit=2&offset=2", headers=headers(mine)).json()
    ids = [job["job_id"] for job in first["jobs"] + second["jobs"]]
    assert len(first["jobs"]) == 2 and len(second["jobs"]) == 2
    assert len(set(ids)) == 4, "pages must not repeat or skip jobs"
    assert set(ids) <= mine_ids
    assert not set(ids) & their_ids
    assert first["total"] == 5


def test_detail_of_another_workers_job_is_unreachable(env):
    client, _, mine, theirs = env
    their_job = submit(client, theirs)
    my_job = submit(client, mine)
    assert client.get(f"/api/me/jobs/{my_job}", headers=headers(mine)).status_code == 200
    resp = client.get(f"/api/me/jobs/{their_job}", headers=headers(mine))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_thumbnail_of_another_workers_job_is_unreachable(env):
    client, _, mine, theirs = env
    their_job = submit(client, theirs)
    my_job = submit(client, mine)
    ok = client.get(f"/api/me/jobs/{my_job}/thumbnail", headers=headers(mine))
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "image/jpeg"
    resp = client.get(f"/api/me/jobs/{their_job}/thumbnail", headers=headers(mine))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_image_of_another_workers_job_is_unreachable(env):
    client, _, mine, theirs = env
    their_job = submit(client, theirs)
    resp = client.get(f"/api/me/jobs/{their_job}/image", headers=headers(mine))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_unknown_job_is_unreachable_on_every_history_route(env):
    client, _, mine, _ = env
    ghost = str(uuid.uuid4())
    for path in ("", "/thumbnail", "/image"):
        resp = client.get(f"/api/me/jobs/{ghost}{path}", headers=headers(mine))
        assert resp.status_code == 404, path


def test_history_requires_an_api_key(env):
    client, *_ = env
    resp = client.get("/api/me/jobs")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
