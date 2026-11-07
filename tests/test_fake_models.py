import base64
import json

import httpx
import pytest

from app import config
from app.ocr_client import OcrClient
from scripts.fake_models import FixtureBook, default_dirs, render_ocr_text, start_fake_models

FIXTURES = config.ROOT / "fixtures"
CLEAN_JSON = FIXTURES / "fis_market_clean.json"
CLEAN_PNG = FIXTURES / "fis_market_clean.png"


def fixture_payload():
    return json.loads(CLEAN_JSON.read_text(encoding="utf-8"))


def image_content(path=CLEAN_PNG):
    data_url = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
    return [
        {"type": "image_url", "image_url": {"url": data_url}},
        {"type": "text", "text": "Table Recognition:"},
    ]


def chat(server, content):
    resp = httpx.post(
        f"{server.base_url}/v1/chat/completions",
        json={"model": "asked-model", "messages": [{"role": "user", "content": content}]},
        timeout=10,
    )
    assert resp.status_code == 200
    return resp.json()


@pytest.fixture(scope="module")
def models():
    servers = start_fake_models([FIXTURES])
    yield servers
    servers.shutdown()


# --- OCR role over real HTTP ---


def test_ocr_role_replays_fixture_table_text(models):
    reply = chat(models.ocr, image_content())
    text = reply["choices"][0]["message"]["content"]
    assert "<fcel>" in text and "<nl>" in text
    assert "BILGIN MARKETLER ANONIM SIRKETI" in text
    assert "Tam buğday ekmeği" in text
    assert "1.046,40" in text  # ara_toplam in printed Turkish form


def test_real_ocr_client_reads_the_stub_over_http(models):
    out = OcrClient(base_url=models.ocr.base_url).transcribe(CLEAN_PNG.read_bytes())
    assert "Zeytinyağı 1L" in out["text"]
    assert out["ms"] >= 0


# --- structuring role over real HTTP ---


def test_structurer_role_returns_the_fixture_json(models):
    ocr_text = chat(models.ocr, image_content())["choices"][0]["message"]["content"]
    reply = chat(models.structurer, ocr_text)
    assert json.loads(reply["choices"][0]["message"]["content"]) == fixture_payload()


def test_structurer_falls_back_to_the_last_served_receipt(models):
    chat(models.ocr, image_content())  # pins fis_market_clean as the last served
    reply = chat(models.structurer, "serbest metin, birebir eşleşmiyor")
    result = json.loads(reply["choices"][0]["message"]["content"])
    assert result["header"]["isim"] == "BILGIN MARKETLER ANONIM SIRKETI"


# --- OpenAI-compatible envelope ---


def test_chat_reply_is_openai_shaped(models):
    reply = chat(models.ocr, image_content())
    assert reply["object"] == "chat.completion"
    assert reply["model"] == "asked-model"
    assert reply["choices"][0]["message"]["role"] == "assistant"
    assert reply["choices"][0]["finish_reason"] == "stop"
    assert set(reply["usage"]) == {"prompt_tokens", "completion_tokens", "total_tokens"}


def test_models_endpoint_lists_the_role_model(models, monkeypatch):
    """Each role reports the id it answers as; strata is the rollback backend."""
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    for server, model in (
        (models.ocr, config.ocr_model_name()),
        (models.structurer, config.strata_model()),
    ):
        resp = httpx.get(f"{server.base_url}/v1/models", timeout=10)
        assert resp.status_code == 200
        assert resp.json()["data"][0]["id"] == model


# --- robustness ---


def test_unknown_image_still_serves_a_fixture(models):
    reply = chat(models.ocr, [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,aGk="}},
    ])
    assert "<fcel>" in reply["choices"][0]["message"]["content"]


def test_invalid_json_body_is_400(models):
    resp = httpx.post(
        f"{models.ocr.base_url}/v1/chat/completions",
        content=b"not json",
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    assert resp.status_code == 400


def test_unknown_path_is_404(models):
    assert httpx.get(f"{models.ocr.base_url}/nope", timeout=10).status_code == 404
    resp = httpx.post(f"{models.ocr.base_url}/v1/completions", json={}, timeout=10)
    assert resp.status_code == 404


def test_servers_listen_on_distinct_ephemeral_ports(models):
    assert models.ocr.port != models.structurer.port
    assert models.ocr.base_url.startswith("http://127.0.0.1:")


# --- fixture book ---


def test_fixture_book_covers_every_ground_truth():
    book = FixtureBook(default_dirs())
    expected = sum(len(list(d.glob("*.json"))) for d in default_dirs())
    assert len(book.fixtures) == expected
    for fx in book.fixtures:
        assert fx.text.startswith("<fcel>")
        assert fx.image_sha is not None
        # clean/foto variants can share one ground truth, so text lookup must
        # return a fixture with the same text, not necessarily the same name
        assert book.for_text(fx.text).text == fx.text


def test_fixture_book_maps_a_fixture_image_to_itself():
    book = FixtureBook([FIXTURES])
    assert book.for_image_bytes(CLEAN_PNG.read_bytes()).name == "fis_market_clean"


def test_fixture_book_rejects_empty_dirs(tmp_path):
    with pytest.raises(ValueError):
        FixtureBook([tmp_path])


def test_rendered_text_holds_items_and_totals():
    text = render_ocr_text(fixture_payload())
    assert "<fcel>Yumurta 15li<fcel>1<fcel>95,00<fcel>95,00<nl>" in text
    assert "<fcel>TOPLAM<fcel>1.192,90<nl>" in text


# --- the boundary rule ---


def test_app_code_never_imports_fake_models():
    hits = [
        path.relative_to(config.ROOT).as_posix()
        for path in (config.ROOT / "app").rglob("*.py")
        if "fake_models" in path.read_text(encoding="utf-8")
    ]
    assert hits == []
