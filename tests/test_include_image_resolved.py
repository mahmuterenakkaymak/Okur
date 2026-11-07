"""T100: STRUCTURER_INCLUDE_IMAGE obeys the backend a call *resolved* to.

PLAN contract 11: the flag is obeyed only by the small backend; Strata and
quality mode always send the receipt. "The small backend" is therefore the
backend this request is built for — ``self.backend`` — and not the one config
happens to deploy. Otherwise ``Structurer(backend="small")`` (or the same with
a ``base_url=`` aimed at the brain, which is how the small-brain gate runs its
--with-image and --no-image arms in one process before the M8 cutover) posts
the photo with the flag at 0 and reports a text-only score measured with the
image attached.
"""
import base64
import json

import httpx
import pytest

from app import config
from app.structurer import MAX_TOKENS, PROMPT, Structurer

IMAGE = b"\xff\xd8\xff\xe0fakejpeg"
OCR_TEXT = "<fcel>BILGIN MARKETLER ANONIM SIRKETI<nl><fcel>ARA TOPLAM<fcel>1.046,40<nl>"
IMAGE_DATA_URL = "data:image/jpeg;base64," + base64.b64encode(IMAGE).decode()
TEXT_PART = {"type": "text", "text": PROMPT + OCR_TEXT}


def chat_ok(request):
    return httpx.Response(200, json={"choices": [{"message": {
        "content": json.dumps({
            "header": {"isim": "BILGIN MARKETLER ANONIM SIRKETI"},
            "items": [{"ad": "Cay", "miktar": 1.0, "birim_fiyat": 12.0, "toplam": 12.0}],
            "totals": {"ara_toplam": 12.0, "iskonto": 0.0, "kdv": 2.0,
                       "kdv_orani": 0.2, "toplam": 14.0},
            "para_birimi": "TRY",
            "okunamayan": [],
        }, ensure_ascii=False),
    }}]})


def route(**kwargs):
    """The single (url, body) a client built from kwargs sent."""
    seen = []

    def handler(request):
        seen.append((str(request.url), json.loads(request.read())))
        return chat_ok(request)

    Structurer(transport=httpx.MockTransport(handler), **kwargs).structure(OCR_TEXT, IMAGE)
    assert len(seen) == 1
    return seen[0]


def content(body):
    return body["messages"][0]["content"]


def parts(**kwargs):
    return [part["type"] for part in content(route(**kwargs)[1])]


# --- the bug: a resolved small backend obeys the flag ---


def test_pinned_small_backend_oboys_the_flag(monkeypatch):
    """backend="small" is the small backend, whatever config deploys (pre-cutover)."""
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "0")
    url, body = route(backend="small")
    assert url == f"{config.small_brain_base_url()}/v1/chat/completions"
    assert body["model"] == config.small_brain_model()
    assert content(body) == [TEXT_PART]


def test_pinned_small_backend_with_a_url_aimed_at_the_brain_is_text_only(monkeypatch):
    """The gate's --no-image arm: same pin, explicit brain url, still no photo."""
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "false")
    url, body = route(backend="small", base_url="http://127.0.0.1:8100", model="vl-4b")
    assert url == "http://127.0.0.1:8100/v1/chat/completions"
    assert body["model"] == "vl-4b"
    assert content(body) == [TEXT_PART]


def test_configured_small_backend_still_oboys_the_flag(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "no")
    assert route() == route(backend="small")
    assert content(route()[1]) == [TEXT_PART]


@pytest.mark.parametrize("value", ["0", "false", "no"])
def test_any_falsy_switch_silences_the_resolved_small_backend(monkeypatch, value):
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", value)
    assert parts(backend="small") == ["text"]


@pytest.mark.parametrize("value", ["1", "true", "", "junk"])
def test_any_truthy_switch_keeps_the_photo_on_the_small_backend(monkeypatch, value):
    """Empty or junk reads as the default (true): the brain reads the receipt."""
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", value)
    assert content(route(backend="small")[1]) == [
        TEXT_PART,
        {"type": "image_url", "image_url": {"url": IMAGE_DATA_URL}},
    ]


def test_both_gate_arms_run_in_one_process(monkeypatch):
    """What scripts/small_brain_gate.py needs: the flag is read per client."""
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "1")
    with_image = Structurer(backend="small", transport=httpx.MockTransport(chat_ok))
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "0")
    without_image = Structurer(backend="small", transport=httpx.MockTransport(chat_ok))
    assert with_image.sends_image is True
    assert without_image.sends_image is False


def test_sends_image_follows_the_resolved_backend(monkeypatch):
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "0")
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    assert Structurer(backend="small").sends_image is False
    assert Structurer(backend="small", quality_mode=True).sends_image is True
    assert Structurer().sends_image is True
    assert Structurer(base_url="http://127.0.0.1:8100").sends_image is True


# --- Strata and quality mode stay byte-identical ---


@pytest.mark.parametrize(
    "kwargs",
    [
        {"backend": "strata"},
        {"backend": "q8"},
        {"backend": "small", "quality_mode": True},
        {"quality_mode": True},
    ],
)
def test_the_flag_changes_nothing_for_strata_or_quality_mode(monkeypatch, kwargs):
    monkeypatch.delenv("STRUCTURER_INCLUDE_IMAGE", raising=False)
    today = route(**kwargs)
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "0")
    assert route(**kwargs) == today
    assert [p["image_url"]["url"] for p in content(today[1]) if p["type"] == "image_url"] == [
        IMAGE_DATA_URL
    ]


def test_config_deploying_strata_does_not_silence_a_pinned_small_backend(monkeypatch):
    """The two directions of the mismatch, both in one request."""
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "1")
    assert parts() == ["text", "image_url"]
    assert parts(backend="small") == ["text", "image_url"]
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "0")
    assert parts() == ["text", "image_url"]
    assert parts(backend="small") == ["text"]


def test_dropping_the_photo_changes_nothing_else_in_the_small_request(monkeypatch):
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "1")
    url_with, with_image = route(backend="small")
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "0")
    url, body = route(backend="small")
    assert url == url_with
    assert {k: v for k, v in body.items() if k != "messages"} == {
        k: v for k, v in with_image.items() if k != "messages"
    }
    assert body["model"] == config.small_brain_model()
    assert body["max_tokens"] == MAX_TOKENS
    assert body["temperature"] == 0
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["messages"][0]["role"] == "user"
