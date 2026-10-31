"""Stage 1: PaddleOCR-VL via llama-server's OpenAI-compatible chat endpoint.

The model server is the only external boundary on this leg: tests inject an
httpx transport and get to replay canned model outputs at the HTTP layer.
"""
from __future__ import annotations

import base64
import time

import httpx

from app import config

PROMPT = "Table Recognition:"
MAX_TOKENS = 1500


class OcrError(RuntimeError):
    """OCR server failure: timeout, connection error, non-2xx or bad payload."""


class OcrClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = config.ocr_base_url() if base_url is None else base_url
        self.timeout = config.ocr_timeout() if timeout is None else timeout
        self._client = httpx.Client(transport=transport, timeout=self.timeout)

    def transcribe(self, image_bytes: bytes, quality_mode: bool = False) -> dict:
        """Raw OCR text for one image, plus elapsed ms.

        ASSUMPTION: quality_mode does not change stage 1 — PaddleOCR-VL serves
        both modes; only stage 2 routes to Unsloth.
        """
        data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode()
        body = {
            "model": config.ocr_model_name(),
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": PROMPT},
                ],
            }],
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
        }
        start = time.perf_counter()
        try:
            resp = self._client.post(f"{self.base_url}/v1/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise OcrError(f"OCR server unreachable: {exc}") from exc
        ms = int((time.perf_counter() - start) * 1000)
        if resp.status_code != 200:
            raise OcrError(f"OCR server returned HTTP {resp.status_code}")
        try:
            text = resp.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise OcrError("malformed OCR response payload") from exc
        return {"text": text, "ms": ms}
