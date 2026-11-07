import base64
import json

import httpx
import pytest

from app import config
from app.structurer import MAX_TOKENS, PROMPT, Structurer, StructurerError, UnreadableError

FIXTURE = config.ROOT / "fixtures" / "fis_market_clean.json"
IMAGE = b"\xff\xd8\xff\xe0fakejpeg"
OCR_TEXT = "<fcel>BILGIN MARKETLER ANONIM SIRKETI<nl><fcel>ARA TOPLAM<fcel>1.046,40<nl>"


def receipt():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def receipt_text():
    return json.dumps(receipt(), ensure_ascii=False)


def chat_ok(content=None):
    def handler(request):
        payload = receipt_text() if content is None else content
        return httpx.Response(200, json={"choices": [{"message": {"content": payload}}]})

    return handler


def make(handler=None, **kwargs):
    transport = httpx.MockTransport(handler or chat_ok())
    return Structurer(transport=transport, **kwargs)


def structure(handler=None, **kwargs):
    return make(handler, **kwargs).structure(OCR_TEXT, IMAGE)


# --- happy path ---


def test_structure_returns_contract_result_and_ms():
    result = structure()
    assert result["header"]["isim"] == "BILGIN MARKETLER ANONIM SIRKETI"
    assert result["items"][0]["ad"] == "Tam buğday ekmeği"
    assert result["totals"]["toplam"] == 1192.9
    assert result["para_birimi"] == "TRY"
    assert isinstance(result["ms"], int) and result["ms"] >= 0


def test_absent_fields_come_back_as_house_defaults():
    result = structure(chat_ok('{"items": [{"ad": "Çay"}]}'))
    assert result["header"] == {"isim": "", "vergi_dairesi": "", "vergi_no": ""}
    assert result["totals"] == {
        "ara_toplam": 0.0,
        "iskonto": 0.0,
        "kdv": 0.0,
        "kdv_orani": 0.0,
        "toplam": 0.0,
    }
    assert result["para_birimi"] == "TRY"
    assert result["okunamayan"] == []
    assert result["items"][0] == {"ad": "Çay", "miktar": 0.0, "birim_fiyat": 0.0, "toplam": 0.0}


def test_printed_amounts_are_normalized_to_floats():
    printed = receipt()
    printed["totals"]["ara_toplam"] = "1.046,40"
    printed["totals"]["kdv_orani"] = "%20"
    printed["items"][0]["miktar"] = "1,033"
    result = structure(chat_ok(json.dumps(printed, ensure_ascii=False)))
    assert result["totals"]["ara_toplam"] == 1046.4
    assert result["totals"]["kdv_orani"] == 0.2
    assert result["items"][0]["miktar"] == 1.033


def test_validation_block_in_the_model_output_never_survives():
    smuggled = receipt()
    smuggled["validation"] = {"verdict": "ok"}
    smuggled["verdict"] = "ok"
    result = structure(chat_ok(json.dumps(smuggled, ensure_ascii=False)))
    assert "validation" not in result
    assert "verdict" not in result


# --- request shape and routing ---


def test_posts_chat_completions_to_strata_port(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    assert config.strata_port() == 8080
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return chat_ok()(request)

    make(handler).structure(OCR_TEXT, IMAGE)
    assert seen == [f"{config.strata_base_url()}/v1/chat/completions"]


def test_uses_strata_model_by_default(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    seen = []

    def handler(request):
        seen.append(json.loads(request.read()))
        return chat_ok()(request)

    make(handler).structure(OCR_TEXT, IMAGE)
    assert seen[0]["model"] == config.strata_model()
    assert seen[0]["temperature"] == 0
    assert seen[0]["max_tokens"] == MAX_TOKENS


def test_thinking_is_disabled_for_the_reasoning_model():
    seen = []

    def handler(request):
        seen.append(json.loads(request.read()))
        return chat_ok()(request)

    make(handler).structure(OCR_TEXT, IMAGE)
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen[0]["max_tokens"] == MAX_TOKENS == 2500


def test_quality_mode_routes_to_unsloth():
    assert config.unsloth_port() == 8888
    seen = []

    def handler(request):
        seen.append((str(request.url), json.loads(request.read())["model"]))
        return chat_ok()(request)

    client = Structurer(quality_mode=True, transport=httpx.MockTransport(handler))
    assert client.quality_mode is True
    client.structure(OCR_TEXT, IMAGE)
    assert seen == [(f"{config.unsloth_base_url()}/v1/chat/completions", config.unsloth_model())]


def test_sends_ocr_text_and_image_together():
    seen = []

    def handler(request):
        seen.append(json.loads(request.read()))
        return chat_ok()(request)

    make(handler).structure(OCR_TEXT, IMAGE)
    parts = seen[0]["messages"][0]["content"]
    texts = [p["text"] for p in parts if p["type"] == "text"]
    images = [p["image_url"]["url"] for p in parts if p["type"] == "image_url"]
    assert texts == [PROMPT + OCR_TEXT]
    expected = "data:image/jpeg;base64," + base64.b64encode(IMAGE).decode()
    assert images == [expected]


def test_prompt_is_the_contract_prompt():
    for field in ("header", "meta", "items", "totals", "para_birimi", "okunamayan"):
        assert field in PROMPT
    for field in ("isim", "vergi_dairesi", "vergi_no", "tarih", "saat", "ad", "miktar",
                  "birim_fiyat", "toplam", "ara_toplam", "iskonto", "kdv", "kdv_orani"):
        assert field in PROMPT
    assert "JSON" in PROMPT


# --- extraction: the model answers in chatter ---


def test_fenced_json_block_is_unwrapped():
    result = structure(chat_ok("İşte fiş:\n```json\n" + receipt_text() + "\n```\nBaşka bir şey?"))
    assert result["header"]["vergi_no"] == "1234567890"


def test_plain_code_fence_without_language():
    result = structure(chat_ok("```\n" + receipt_text() + "\n```"))
    assert result["items"][0]["ad"] == "Tam buğday ekmeği"


def test_trailing_commas_are_repaired():
    sloppy = '{"items": [{"ad": "Çay", "miktar": 1.0, "toplam": 12.0,},], "totals": {"toplam": 12.0,},}'
    result = structure(chat_ok(sloppy))
    assert result["items"][0]["toplam"] == 12.0
    assert result["totals"]["toplam"] == 12.0


def test_reasoning_block_is_stripped_before_the_json():
    content = (
        "<think>KDV %20 görünüyor, {ara_toplam} toplamı tutuyor.</think>" + receipt_text()
    )
    result = structure(chat_ok(content))
    assert result["totals"]["kdv"] == 198.82


def test_reasoning_block_after_the_json_is_stripped():
    content = receipt_text() + "\n<thinking>burada düşünce yazısı var</thinking>"
    result = structure(chat_ok(content))
    assert result["header"]["isim"] == "BILGIN MARKETLER ANONIM SIRKETI"


def test_unpaired_reasoning_tags_are_dropped():
    result = structure(chat_ok("</think>" + receipt_text()))
    assert result["items"]


def test_sentences_around_the_object_are_ignored():
    content = "Fiş içeriği aşağıdadır.\n" + receipt_text() + "\nBaşka bir isteğiniz var mı?"
    result = structure(chat_ok(content))
    assert result["totals"]["ara_toplam"] == 1046.4


def test_empty_ocr_text_is_still_a_request():
    seen = []

    def handler(request):
        seen.append(json.loads(request.read()))
        return chat_ok()(request)

    make(handler).structure("", IMAGE)
    texts = [p["text"] for p in seen[0]["messages"][0]["content"] if p["type"] == "text"]
    assert texts == [PROMPT]


# --- unreadable: output that cannot become a result ---


@pytest.mark.parametrize(
    "content",
    [
        "Fişi okuyamadım, lütfen daha yakın çekin.",
        "",
        "[1, 2, 3]",
        '{"error": "görsel okunamadı"}',
        '{"unbalanced": {"items": [',
    ],
)
def test_output_that_cannot_become_a_result_raises_unreadable(content):
    with pytest.raises(UnreadableError):
        structure(chat_ok(content))


def test_items_that_are_not_product_lines_raises_unreadable():
    broken = receipt()
    broken["items"] = [120.0, 85.5]
    with pytest.raises(UnreadableError):
        structure(chat_ok(json.dumps(broken, ensure_ascii=False)))


def test_totals_of_the_wrong_shape_raises_unreadable():
    broken = receipt()
    broken["totals"] = "1192,90 TL"
    with pytest.raises(UnreadableError):
        structure(chat_ok(json.dumps(broken, ensure_ascii=False)))


def test_answer_of_only_thoughts_is_unreadable_not_a_crash():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {
            "content": None,
            "reasoning_content": "Kullanıcı fişteki firma adını soruyor. "
                                 "Görseli dikkatlice inceleyeyim.",
        }}]})

    with pytest.raises(UnreadableError):
        structure(handler)


def test_unreadable_reason_reaches_the_caller():
    with pytest.raises(UnreadableError, match="no JSON object"):
        structure(chat_ok("okuyamadım"))


# --- server failures are a different reason than an unreadable receipt ---


@pytest.mark.parametrize("exc", [httpx.ConnectTimeout("boom"), httpx.ReadTimeout("slow")])
def test_timeout_raises_structurer_error(exc):
    def handler(request):
        raise exc

    with pytest.raises(StructurerError) as caught:
        structure(handler)
    assert not isinstance(caught.value, UnreadableError)


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_raises_structurer_error(status):
    def handler(request):
        return httpx.Response(status, text="kaput")

    with pytest.raises(StructurerError) as caught:
        structure(handler)
    assert str(status) in str(caught.value)
    assert not isinstance(caught.value, UnreadableError)


def test_connection_error_raises_structurer_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(StructurerError):
        structure(handler)


@pytest.mark.parametrize(
    "payload",
    [b"not json", b'{"choices": []}', b'{"choices": [{"message": {}}]}'],
)
def test_malformed_payload_raises_structurer_error(payload):
    def handler(request):
        return httpx.Response(200, content=payload)

    with pytest.raises(StructurerError):
        structure(handler)


# --- config wiring ---


def test_timeout_defaults_to_config():
    assert make().timeout == config.structurer_timeout()


def test_default_server_is_strata(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    client = make()
    assert client.base_url == config.strata_base_url()
    assert client.model == config.strata_model()


def test_quality_mode_defaults_to_off():
    assert make().quality_mode is False


def test_explicit_base_url_model_and_timeout_override_routing():
    client = Structurer(
        quality_mode=True,
        base_url="http://model.test:9999",
        model="deneme",
        timeout=1.5,
        transport=httpx.MockTransport(chat_ok()),
    )
    assert client.base_url == "http://model.test:9999"
    assert client.model == "deneme"
    assert client.timeout == 1.5


# --- stage-2 backend selection (T71) ---


def capture():
    """(seen, handler): handler records (url, body) per request and answers ok."""
    seen = []

    def handler(request):
        seen.append((str(request.url), json.loads(request.read())))
        return chat_ok()(request)

    return seen, handler


def route(**kwargs):
    """The single (url, body) a client built from kwargs sent."""
    seen, handler = capture()
    make(handler, **kwargs).structure(OCR_TEXT, IMAGE)
    assert len(seen) == 1
    return seen[0]


def test_backend_defaults_to_config_structurer_backend(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    assert make().backend == config.structurer_backend() == "strata"
    monkeypatch.setenv("STRUCTURER_BACKEND", "q8")
    assert make().backend == config.DEFAULT_STRUCTURER_BACKEND == config.structurer_backend()


def test_config_can_select_the_small_backend(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    assert route() == (
        f"{config.small_brain_base_url()}/v1/chat/completions",
        route(backend="small")[1],
    )


def test_small_backend_sends_the_same_request_to_the_small_brain():
    url, body = route(backend="small")
    assert url == f"{config.small_brain_base_url()}/v1/chat/completions"
    assert body["model"] == config.small_brain_model()


def test_small_backend_follows_its_own_env(monkeypatch):
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", "http://10.0.0.5:9111")
    monkeypatch.setenv("SMALL_BRAIN_MODEL", "vl-4b-iq4")
    assert route(backend="small") == (
        "http://10.0.0.5:9111/v1/chat/completions",
        {**route(backend="small")[1], "model": "vl-4b-iq4"},
    )


def test_strata_backend_is_the_default_route(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    assert route(backend="strata") == route()
    assert route(backend="strata")[0] == f"{config.strata_base_url()}/v1/chat/completions"
    assert route(backend="strata")[1]["model"] == config.strata_model()


@pytest.mark.parametrize("value", [" SMALL ", "small"])
def test_backend_names_ignore_case_and_padding(value):
    assert make(backend=value).backend == "small"


@pytest.mark.parametrize("value", ["", "  ", "q8", "strata-80b", "small brain"])
def test_unknown_backend_falls_back_to_strata(value):
    url, body = route(backend=value)
    assert make(backend=value).backend == "strata"
    assert url == f"{config.strata_base_url()}/v1/chat/completions"
    assert body["model"] == config.strata_model()


def test_quality_mode_beats_the_backend(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    for kwargs in ({"quality_mode": True}, {"quality_mode": True, "backend": "small"}):
        url, body = route(**kwargs)
        assert url == f"{config.unsloth_base_url()}/v1/chat/completions"
        assert body["model"] == config.unsloth_model()


def test_quality_mode_backend_is_reported_as_strata_when_unset():
    assert make(quality_mode=True).backend == config.DEFAULT_STRUCTURER_BACKEND


@pytest.mark.parametrize(
    "kwargs", [{}, {"backend": "strata"}, {"backend": "small"}, {"quality_mode": True}]
)
def test_every_backend_sends_the_same_body(kwargs):
    _, body = route(**kwargs)
    parts = body["messages"][0]["content"]
    assert [p["text"] for p in parts if p["type"] == "text"] == [PROMPT + OCR_TEXT]
    assert [p["image_url"]["url"] for p in parts if p["type"] == "image_url"] == [
        "data:image/jpeg;base64," + base64.b64encode(IMAGE).decode()
    ]
    assert body["max_tokens"] == MAX_TOKENS
    assert body["temperature"] == 0
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


def test_include_image_is_read_when_the_client_is_built(monkeypatch):
    """Read once, at build time, from the backend this client resolved to."""
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "false")
    seen, handler = capture()
    client = make(handler, backend="small")
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "1")
    assert client.sends_image is False
    client.structure(OCR_TEXT, IMAGE)
    assert [p["type"] for p in content(seen[0][1])] == ["text"]


# --- include_image: the deployed small brain alone reads text-only (T82) ---


IMAGE_DATA_URL = "data:image/jpeg;base64," + base64.b64encode(IMAGE).decode()


def content(body):
    return body["messages"][0]["content"]


def test_include_image_off_sends_the_small_brain_prompt_plus_text_only(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "0")
    url, body = route()
    assert url == f"{config.small_brain_base_url()}/v1/chat/completions"
    assert content(body) == [{"type": "text", "text": PROMPT + OCR_TEXT}]


@pytest.mark.parametrize("value", ["0", "false", "no"])
def test_any_falsy_switch_silences_the_image_on_the_small_brain(monkeypatch, value):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", value)
    assert [p["type"] for p in content(route()[1])] == ["text"]


@pytest.mark.parametrize("value", ["1", "true"])
def test_include_image_on_keeps_the_small_brain_multimodal(monkeypatch, value):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", value)
    assert content(route()[1]) == [
        {"type": "text", "text": PROMPT + OCR_TEXT},
        {"type": "image_url", "image_url": {"url": IMAGE_DATA_URL}},
    ]


def test_include_image_off_changes_nothing_else_in_the_small_request(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    url_with_image, with_image = route()
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "0")
    url, body = route()
    assert url == url_with_image
    assert {k: v for k, v in body.items() if k != "messages"} == {
        k: v for k, v in with_image.items() if k != "messages"
    }
    assert body["model"] == config.small_brain_model()
    assert body["max_tokens"] == MAX_TOKENS
    assert body["temperature"] == 0
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["messages"][0]["role"] == "user"
    assert [p["type"] for p in content(with_image)] == ["text", "image_url"]


@pytest.mark.parametrize(
    "kwargs",
    [{"backend": "strata"}, {"quality_mode": True}, {"backend": "small", "quality_mode": True}],
)
def test_include_image_off_never_touches_strata_or_quality_mode(monkeypatch, kwargs):
    """Flag off, request unchanged: Strata and Unsloth still read the receipt."""
    today = route(**kwargs)
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "0")
    assert route(**kwargs) == today
    assert [p["image_url"]["url"] for p in content(today[1]) if p["type"] == "image_url"] == [
        IMAGE_DATA_URL
    ]


def test_a_pinned_backend_is_the_switch_speaks_too(monkeypatch):
    """The flag follows the resolved backend, not the one config deploys (T100)."""
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "0")
    assert [p["type"] for p in content(route(backend="small")[1])] == ["text"]
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    assert [p["type"] for p in content(route()[1])] == ["text"]
