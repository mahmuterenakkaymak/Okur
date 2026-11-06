"""OpenAI-compatible stub servers for the two model roles — smoke and demo only.

Serves the committed fixtures' ground truth over real HTTP so smokes and the
demo exercise real sockets, the real queue and the real pipeline: the OCR role
replays Paddle-style table text rendered from a fixture, the structuring role
answers with the fixture JSON itself. App code must never import this module.

Run standalone (prints both URLs, Ctrl+C to stop):
    python -m scripts.fake_models
"""
from __future__ import annotations

import base64
import hashlib
import itertools
import json
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from app import config

CHAT_PATH = "/v1/chat/completions"
MODELS_PATH = "/v1/models"


def default_dirs() -> list[Path]:
    return [
        config.ROOT / name
        for name in ("fixtures", "fixtures_hard")
        if (config.ROOT / name).is_dir()
    ]


def _tr(value: Any) -> str:
    """Amount in the printed Turkish form: 1.046,40."""
    number = float(value or 0)
    text = f"{abs(number):,.2f}"
    text = text.replace(",", "X").replace(".", ",").replace("X", ".")
    return text if number >= 0 else "-" + text


def _qty(value: Any) -> str:
    number = float(value or 0)
    return str(int(number)) if number.is_integer() else _tr(number)


def render_ocr_text(result: dict) -> str:
    """Ground-truth result as PaddleOCR-VL 'Table Recognition' style text."""
    header = result.get("header") or {}
    meta = result.get("meta") or {}
    totals = result.get("totals") or {}
    lines = [
        f"<fcel>{header.get('isim', '')}<nl>",
        f"<fcel>V.D {header.get('vergi_dairesi', '')}"
        f"<fcel>V.NO {header.get('vergi_no') or result.get('vergi_no', '')}<nl>",
        f"<fcel>{meta.get('tarih') or result.get('tarih', '')}"
        f"<fcel>{meta.get('saat', '')}<fcel>{meta.get('no', '')}<nl>",
    ]
    keywords = result.get("keywords")
    if keywords:
        lines.append("".join(f"<fcel>{kw}" for kw in keywords) + "<nl>")
    else:
        lines.append("<fcel>MAL<fcel>MIKTAR<fcel>B.FIYAT<fcel>TUTAR<nl>")
    for item in result.get("items") or []:
        if isinstance(item, dict):
            lines.append(
                f"<fcel>{item.get('ad', '')}<fcel>{_qty(item.get('miktar'))}"
                f"<fcel>{_tr(item.get('birim_fiyat'))}<fcel>{_tr(item.get('toplam'))}<nl>"
            )
        else:
            # fixtures_hard/fis_kotu_cekim ground truth keeps amounts only.
            lines.append(f"<fcel>{_tr(item)}<nl>")
    lines.append(f"<fcel>ARA TOPLAM<fcel>{_tr(totals.get('ara_toplam'))}<nl>")
    lines.append(f"<fcel>ISKONTO<fcel>{_tr(totals.get('iskonto'))}<nl>")
    lines.append(f"<fcel>KDV<fcel>{_tr(totals.get('kdv'))}<nl>")
    lines.append(f"<fcel>TOPLAM<fcel>{_tr(totals.get('toplam'))}<nl>")
    return "".join(lines)


@dataclass
class Fixture:
    name: str
    result: dict
    text: str
    image_sha: str | None


class FixtureBook:
    """All fixture ground truths, reachable by image bytes and by OCR text."""

    def __init__(self, dirs):
        self.fixtures: list[Fixture] = []
        for directory in dirs:
            for path in sorted(Path(directory).glob("*.json")):
                result = json.loads(path.read_text(encoding="utf-8"))
                png = path.with_suffix(".png")
                self.fixtures.append(
                    Fixture(
                        name=path.stem,
                        result=result,
                        text=render_ocr_text(result),
                        image_sha=(
                            hashlib.sha256(png.read_bytes()).hexdigest()
                            if png.exists()
                            else None
                        ),
                    )
                )
        if not self.fixtures:
            raise ValueError(f"no fixture ground truth found in {list(dirs)}")
        self._by_image = {f.image_sha: f for f in self.fixtures if f.image_sha}
        self._by_text = {f.text: f for f in self.fixtures}
        self._lock = threading.Lock()
        self._cycle = itertools.cycle(self.fixtures)
        self._last = self.fixtures[0]

    def for_image_bytes(self, data: bytes) -> Fixture:
        known = self._by_image.get(hashlib.sha256(data).hexdigest())
        with self._lock:
            self._last = known or next(self._cycle)
        return self._last

    def for_text(self, text: str) -> Fixture:
        with self._lock:
            # ASSUMPTION: the stage-2 prompt may wrap the OCR text in
            # instructions, so an unknown text falls back to the fixture the
            # OCR role served last — the pair a real pipeline run always is.
            return self._by_text.get(text) or self._last


def _completion(model: str, content: str) -> dict:
    return {
        "id": "chatcmpl-fake-models",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _last_message(body: dict) -> tuple[str, str]:
    """(image data url, joined text) of the last message, either may be empty."""
    messages = body.get("messages") or [{}]
    content = messages[-1].get("content")
    if isinstance(content, str):
        return "", content
    image, texts = "", []
    for part in content or []:
        if part.get("type") == "image_url":
            image = (part.get("image_url") or {}).get("url", "")
        elif part.get("type") == "text":
            texts.append(part.get("text", ""))
    return image, "\n".join(texts)


def _image_bytes(data_url: str) -> bytes:
    payload = data_url.rsplit(",", 1)[-1] if "," in data_url else data_url
    try:
        return base64.b64decode(payload, validate=False)
    except (ValueError, TypeError):
        return b""


def _model_id(role: str) -> str:
    """The model this role answers as — stage 2 is whichever backend resolves.

    ASSUMPTION: one stub server serves one stage-2 route at a time and quality
    mode is not run through it, so the resolved non-quality model is its id.
    """
    return config.ocr_model_name() if role == "ocr" else config.stage2_model(False)


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != CHAT_PATH:
            return self._json(404, {"error": {"message": f"no {self.path}"}})
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._json(400, {"error": {"message": "invalid JSON body"}})
        image, text = _last_message(body)
        book: FixtureBook = self.server.book
        if self.server.role == "ocr":
            content = book.for_image_bytes(_image_bytes(image)).text
        else:
            content = json.dumps(book.for_text(text).result, ensure_ascii=False)
        self._json(200, _completion(str(body.get("model") or _model_id(self.server.role)), content))

    def do_GET(self):
        if self.path != MODELS_PATH:
            return self._json(404, {"error": {"message": f"no {self.path}"}})
        self._json(200, {
            "object": "list",
            "data": [{
                "id": _model_id(self.server.role),
                "object": "model",
                "created": 0,
                "owned_by": "fake-models",
            }],
        })

    def _json(self, status: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class FakeModelServer:
    """One role on a real socket; port 0 picks an ephemeral port."""

    def __init__(self, role: str, book: FixtureBook, host: str = "127.0.0.1", port: int = 0):
        self.role = role
        self._httpd = ThreadingHTTPServer((host, port), _Handler)
        self._httpd.book = book
        self._httpd.role = role
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://{self._httpd.server_address[0]}:{self.port}"

    def shutdown(self):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


class FakeModels:
    def __init__(self, ocr: FakeModelServer, structurer: FakeModelServer):
        self.ocr = ocr
        self.structurer = structurer

    def shutdown(self):
        self.ocr.shutdown()
        self.structurer.shutdown()


def start_fake_models(dirs=None, host: str = "127.0.0.1") -> FakeModels:
    book = FixtureBook(default_dirs() if dirs is None else dirs)
    return FakeModels(
        FakeModelServer("ocr", book, host),
        FakeModelServer("structurer", book, host),
    )


if __name__ == "__main__":
    models = start_fake_models()
    print(f"OCR stub:        {models.ocr.base_url}")
    print(f"Structurer stub: {models.structurer.base_url}")
    print("Ctrl+C to stop")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        models.shutdown()
