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


def test_posts_chat_completions_to_strata_port():
    assert config.strata_port() == 8080
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return chat_ok()(request)

    make(handler).structure(OCR_TEXT, IMAGE)
    assert seen == [f"{config.strata_base_url()}/v1/chat/completions"]


def test_uses_strata_model_by_default():
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


def test_default_server_is_strata():
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
