import base64
import json

import httpx
import pytest

from app import config
from app.ocr_client import MAX_TOKENS, PROMPT, OcrClient, OcrError

IMAGE = b"\xff\xd8\xff\xe0fakejpeg"
REPLY = "<table>ŞOK Market<nl>1,033Kg FINİX<ecel></table>"


def chat_ok(content=REPLY):
    def handler(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    return handler


def make_client(handler=None, **kwargs):
    transport = httpx.MockTransport(handler or chat_ok())
    return OcrClient(transport=transport, **kwargs)


# --- happy path ---


def test_transcribe_returns_text_and_ms():
    result = make_client().transcribe(IMAGE)
    assert result["text"] == REPLY
    assert isinstance(result["ms"], int) and result["ms"] >= 0


def test_quality_mode_accepted_and_uses_same_endpoint():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return chat_ok()(request)

    result = make_client(handler).transcribe(IMAGE, quality_mode=True)
    assert result["text"] == REPLY
    assert seen == ["/v1/chat/completions"]


# --- request shape ---


def test_posts_chat_completions_to_ocr_port():
    assert config.ocr_port() == 8081
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return chat_ok()(request)

    client = OcrClient(transport=httpx.MockTransport(handler))
    client.transcribe(IMAGE)
    assert seen == [f"{config.ocr_base_url()}/v1/chat/completions"]


def test_image_becomes_base64_data_url():
    seen = []

    def handler(request):
        seen.append(request.read())
        return chat_ok()(request)

    make_client(handler).transcribe(IMAGE)
    parts = json.loads(seen[0])["messages"][0]["content"]
    image_part = next(p for p in parts if p["type"] == "image_url")
    expected = "data:image/jpeg;base64," + base64.b64encode(IMAGE).decode()
    assert image_part["image_url"]["url"] == expected


def test_uses_paddle_table_recognition_prompt():
    seen = []

    def handler(request):
        seen.append(json.loads(request.read()))
        return chat_ok()(request)

    make_client(handler).transcribe(IMAGE)
    body = seen[0]
    parts = body["messages"][0]["content"]
    texts = [p["text"] for p in parts if p["type"] == "text"]
    assert texts == [PROMPT] == ["Table Recognition:"]
    assert body["temperature"] == 0
    assert body["max_tokens"] == MAX_TOKENS
    assert body["model"] == config.ocr_model_name()


# --- timeouts and server errors ---


@pytest.mark.parametrize("exc", [httpx.ConnectTimeout("boom"), httpx.ReadTimeout("slow")])
def test_timeout_raises_ocr_error(exc):
    def handler(request):
        raise exc

    with pytest.raises(OcrError):
        make_client(handler).transcribe(IMAGE)


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_raises_ocr_error(status):
    def handler(request):
        return httpx.Response(status, text="kaput")

    with pytest.raises(OcrError):
        make_client(handler).transcribe(IMAGE)


def test_connection_error_raises_ocr_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(OcrError):
        make_client(handler).transcribe(IMAGE)


@pytest.mark.parametrize(
    "payload",
    [b"not json", b'{"choices": []}', b'{"choices": [{"message": {}}]}'],
)
def test_malformed_payload_raises_ocr_error(payload):
    def handler(request):
        return httpx.Response(200, content=payload)

    with pytest.raises(OcrError):
        make_client(handler).transcribe(IMAGE)


# --- config wiring ---


def test_timeout_defaults_to_config():
    assert make_client().timeout == config.ocr_timeout()


def test_explicit_timeout_and_base_url_override():
    client = make_client(timeout=1.5, base_url="http://model.test:9999")
    assert client.timeout == 1.5
    assert client.base_url == "http://model.test:9999"
