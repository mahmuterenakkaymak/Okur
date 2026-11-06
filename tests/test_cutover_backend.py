"""M8 cutover: the small brain is stage 2 by default, Strata is the rollback.

config's default is the one place the backend is decided (PLAN contract 11), so
this pins the three things the flip is allowed to change: no env means stage 2
runs on the small brain, one env puts Strata back and sends *today's exact
request*, and the smoke/demo follow the resolved model instead of the Strata id.
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from app import auth, config, db
from app.structurer import MAX_TOKENS, PROMPT, Structurer
from scripts import serve_demo
from scripts import smoke_e2e as smoke

IMAGE = b"\xff\xd8\xff\xe0fakejpeg"
OCR_TEXT = "<fcel>BILGIN MARKETLER<nl>"
STUB_URL = "http://127.0.0.1:5599"

# Every stage-2 key, so "no env" really means no env.
STAGE2_ENV = (
    "STRUCTURER_BACKEND",
    "STRUCTURER_INCLUDE_IMAGE",
    "STRATA_HOST",
    "STRATA_PORT",
    "STRATA_MODEL",
    "UNSLOTH_MODEL",
    "SMALL_BRAIN_BASE_URL",
    "SMALL_BRAIN_MODEL",
)


@pytest.fixture(autouse=True)
def bare_stage2_env(monkeypatch):
    for name in STAGE2_ENV:
        monkeypatch.delenv(name, raising=False)


def route(**kwargs) -> tuple[str, dict]:
    """(url, body) of the request a shipped Structurer sends."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"items": [{"ad": "Çay"}]}'}}]},
        )

    Structurer(transport=httpx.MockTransport(handle), **kwargs).structure(OCR_TEXT, IMAGE)
    request = seen[0]
    return str(request.url), json.loads(request.content)


# --- the new default ---


def test_no_env_runs_stage2_on_the_small_brain():
    assert config.DEFAULT_STRUCTURER_BACKEND == "small"
    assert config.structurer_backend() == "small"
    assert config.stage2_model(False) == config.small_brain_model()


def test_the_default_request_goes_to_the_small_brain():
    url, body = route()
    assert url == f"{config.small_brain_base_url()}/v1/chat/completions"
    assert body["model"] == config.small_brain_model()
    assert [part["type"] for part in body["messages"][0]["content"]] == [
        "text",
        "image_url",
    ]


# --- the rollback ---


def test_strata_backend_sends_todays_exact_request():
    url, body = route(backend="strata")
    assert url == f"{config.strata_base_url()}/v1/chat/completions"
    assert body == {
        "model": config.strata_model(),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT + OCR_TEXT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/jpeg;base64,"
                            + base64.b64encode(IMAGE).decode()
                        },
                    },
                ],
            }
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }


def test_the_rollback_is_one_env_value(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    assert config.structurer_backend() == "strata"
    assert config.stage2_model(False) == config.strata_model()
    assert Structurer().base_url == config.strata_base_url()
    assert route() == route(backend="strata")


# --- the env blocks that follow the flip ---


def test_the_smoke_moves_whichever_stage2_server_config_picked():
    saved = smoke._stage2_env(STUB_URL)
    assert set(saved) == {"STRATA_HOST", "STRATA_PORT", "SMALL_BRAIN_BASE_URL"}
    assert config.small_brain_base_url() == STUB_URL
    assert config.strata_base_url() == STUB_URL


def test_the_demo_seeds_the_model_that_will_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    conn = db.connect(tmp_path / "demo.db")
    try:
        key_id, _ = auth.create_key(conn, "demo")
        jobs = serve_demo.seed_jobs(conn, key_id=key_id, images_dir=tmp_path / "images")
    finally:
        conn.close()
    finished = [job for job in jobs if job["status"] == "done"]
    assert finished, "the demo seeded nothing that finished a run"
    assert {json.loads(job["meta_json"])["model"] for job in finished} == {
        config.stage2_model(False)
    }
