"""T64: the daily check has a way in that a real instance actually answers.

_live() used to read the worker key off /demo/config.json, an endpoint only
serve_demo serves, so OPERATIONS.md's `--base-url` command died on its first row
against every deployment. Pinned here: the key's three ways in (--api-key,
OCR_ACCEPTANCE_KEY, the demo handshake) and the two doc commands that promise
them. No test opens a socket.
"""
from __future__ import annotations

import pathlib
import re

import httpx

from scripts import acceptance

ROOT = pathlib.Path(__file__).resolve().parents[1]
OPERATIONS = (ROOT / "OPERATIONS.md").read_text(encoding="utf-8")
_FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.S | re.M)

REAL_INSTANCE = "http://127.0.0.1:8090"
DEAD_URL = "http://127.0.0.1:1"
KEY = "ocrk_" + "a" * 40
ENV_KEY = "ocrk_" + "b" * 40
CLI_KEY = "ocrk_" + "c" * 40


def _fake_get(monkeypatch, status: int, payload: dict | None = None) -> list[str]:
    """What the instance answers on /demo/config.json, and every URL it was asked."""
    asked: list[str] = []

    def fake_get(url, **kwargs):
        asked.append(url)
        return httpx.Response(status, json=payload or {}, request=httpx.Request("GET", url))

    monkeypatch.setattr(acceptance.httpx, "get", fake_get)
    return asked


def _stop_at_live(monkeypatch) -> dict:
    """main()'s live target, recording the key it was handed and going no further."""
    seen: dict = {}

    def fake_live(base_url, api_key):
        seen["base_url"] = base_url
        seen["api_key"] = api_key
        raise acceptance.CheckError("stop before the checks")

    monkeypatch.setattr(acceptance, "_live", fake_live)
    return seen


# --- the key's three ways in ---


def test_a_given_key_never_probes_the_demo_endpoint(monkeypatch):
    asked = _fake_get(monkeypatch, 404)  # what a real instance answers
    inst = acceptance._live(REAL_INSTANCE, KEY)
    try:
        assert inst.api_key == KEY
        assert asked == []
    finally:
        inst.close()


def test_a_demo_instance_still_hands_its_key_over(monkeypatch):
    asked = _fake_get(monkeypatch, 200, {"api_key": KEY})
    inst = acceptance._live(REAL_INSTANCE, "")
    try:
        assert inst.api_key == KEY
        assert asked == [f"{REAL_INSTANCE}/demo/config.json"]
    finally:
        inst.close()


def test_the_keyless_failure_names_the_flag_that_fixes_it(monkeypatch, capsys):
    monkeypatch.delenv("OCR_ACCEPTANCE_KEY", raising=False)
    _fake_get(monkeypatch, 404)
    assert acceptance.main(["--base-url", REAL_INSTANCE]) == 1
    out = capsys.readouterr().out
    assert "instance up" in out
    assert "--api-key" in out and "OCR_ACCEPTANCE_KEY" in out


def test_the_env_key_is_the_default_for_the_flag(monkeypatch):
    monkeypatch.setenv("OCR_ACCEPTANCE_KEY", ENV_KEY)
    seen = _stop_at_live(monkeypatch)
    assert acceptance.main(["--base-url", DEAD_URL]) == 1
    assert seen["api_key"] == ENV_KEY


def test_the_command_line_key_beats_the_env(monkeypatch):
    monkeypatch.setenv("OCR_ACCEPTANCE_KEY", ENV_KEY)
    seen = _stop_at_live(monkeypatch)
    acceptance.main(["--base-url", DEAD_URL, "--api-key", CLI_KEY])
    assert seen["api_key"] == CLI_KEY


def test_no_key_at_all_reaches_the_demo_handshake_as_empty(monkeypatch):
    monkeypatch.delenv("OCR_ACCEPTANCE_KEY", raising=False)
    seen = _stop_at_live(monkeypatch)
    acceptance.main(["--base-url", DEAD_URL])
    assert seen["api_key"] == ""


# --- the documented commands carry a key ---


def test_every_documented_live_check_carries_a_key():
    blocks = [block for _, block in _FENCE.findall(OPERATIONS)]
    live = [block for block in blocks if "acceptance.py --base-url" in block]
    assert len(live) == 2, "OPERATIONS.md documents the live check twice"
    for block in live:
        assert "OCR_ACCEPTANCE_KEY" in block or "--api-key" in block, block
