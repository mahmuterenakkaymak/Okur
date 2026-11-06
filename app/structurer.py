"""Stage 2: OCR text plus the receipt image in, contract v1 result out.

The language layer's whole job is this one leg: Strata :8080 turns stage 1's raw
text into the contract object, and quality mode hands the same request to
Unsloth Studio :8888. Nothing here computes — amounts are transcribed as
printed and normalized by the contract, the validator owns the arithmetic.

Model chatter is the reason the extraction is defensive: a reasoning block, a
```json fence, a trailing comma or a sentence before the object are all normal
for a chat model, and each one would otherwise read as an unreadable receipt.
"""
from __future__ import annotations

import base64
import json
import re
import time
from typing import Any

import httpx
from pydantic import ValidationError

from app import config, contract

MAX_TOKENS = 2500

PROMPT = """Bir fişin görselini ve o görselden çıkarılmış OCR metnini aşağısı gibi tek bir JSON nesnesine çevir:
{"header":{"isim":"","vergi_dairesi":"","vergi_no":""},\
"meta":{"tarih":"dd.MM.yyyy","saat":"HH:mm","no":"","tip":""},\
"items":[{"ad":"","miktar":0.0,"birim_fiyat":0.0,"toplam":0.0}],\
"totals":{"ara_toplam":0.0,"iskonto":0.0,"kdv":0.0,"kdv_orani":0.0,"toplam":0.0},\
"para_birimi":"TRY","okunamayan":[]}

Kurallar:
- Yanıtın yalnızca bu JSON nesnesi olsun; açıklama, yorum veya soru yazma.
- Alan adlarını ve sırasını bozma. Okuyamadığın alanı uydurma; varsayılanında bırak: metin "", sayı 0.0, liste [].
- Tutarları fişin yazdığı değeriyle ver, toplama/çıkarma yapma: "1.046,40" -> 1046.40, "149,00-" -> -149.00.
- kdv_orani kesir olarak verilir: %20 -> 0.2, %8,5 -> 0.085.
- miktar kilogram ise 3 ondalık basamakla yaz: 1,033Kg -> 1.033.
- Fişteki iskonto satırı negatif de basılmış olabilir; iskonto alanına mutlak değerini yaz.
- Hiç okuyamadığın parçaları okunamayan listesine aynen yaz.

OCR metni:
"""

# A chat model's answer rarely arrives as bare JSON: reasoning first, then a
# fence, then the object with one comma too many.
_TAGS_RE = re.compile(r"</?(?:think|thinking|thought|reasoning)\b[^>]*>", re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json|javascript)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_RESULT_FIELDS = frozenset({"header", "meta", "items", "totals", "para_birimi", "okunamayan"})
_BACKENDS = frozenset({"small", "strata"})

# What a job says when stage 2 has no brain to call (PLAN run-2 R5): the fix is
# one command, so the sentence names it and lands in the job's error column,
# the admin detail and the phone's failure line.
NOT_INSTALLED = "small brain not installed — çalıştırmak için scripts\\install_small_brain.ps1"


class StructurerError(RuntimeError):
    """Structuring server failure: timeout, connection error, non-2xx, bad payload."""


class UnreadableError(StructurerError):
    """Model output that cannot become a schema-valid contract result."""


def _resolve_backend(backend: str | None) -> str:
    """backend=None reads config; an unknown value is today's path: strata.

    config.structurer_include_image() is deliberately not read here: the flag
    decides *whether* the small backend sends the image, and that is M7's work.
    """
    value = (config.structurer_backend() if backend is None else backend)
    value = value.strip().lower()
    return value if value in _BACKENDS else "strata"


class Structurer:
    def __init__(
        self,
        quality_mode: bool = False,
        backend: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        # ASSUMPTION: quality mode is a stage-2 routing concern (PLAN "stage 2:
        # Strata :8080 (quality mode: Unsloth :8888)"), so it picks the server
        # here, wins over the backend, and never reaches structure().
        self.quality_mode = quality_mode
        self.backend = _resolve_backend(backend)
        if quality_mode:
            server_url, server_model = config.unsloth_base_url(), config.unsloth_model()
        elif self.backend == "small":
            server_url, server_model = (
                config.small_brain_base_url(),
                config.small_brain_model(),
            )
        else:
            server_url, server_model = config.strata_base_url(), config.strata_model()
        self.base_url = server_url if base_url is None else base_url
        self.model = server_model if model is None else model
        # Only this request can meet a brain that was never installed: Strata
        # and quality mode's Unsloth are separate servers in separate places.
        self.uses_small_brain = self.backend == "small" and not quality_mode
        self.timeout = config.structurer_timeout() if timeout is None else timeout
        self._client = httpx.Client(transport=transport, timeout=self.timeout)

    def structure(self, ocr_text: str, image_bytes: bytes) -> dict[str, Any]:
        """Contract-shaped result plus elapsed ms; UnreadableError on junk output."""
        data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode()
        body = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT + (ocr_text or "")},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
            # Strata is a reasoning model: left on, it spends the whole budget on
            # reasoning_content and answers content=null, so every real receipt
            # reads as unreadable. This is the flag that turns it off.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        start = time.perf_counter()
        try:
            resp = self._client.post(f"{self.base_url}/v1/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise StructurerError(self._unreachable(exc)) from exc
        ms = int((time.perf_counter() - start) * 1000)
        if resp.status_code != 200:
            raise StructurerError(f"structuring server returned HTTP {resp.status_code}")
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise StructurerError("malformed structuring response payload") from exc
        return {**self._result(str(content)), "ms": ms}

    def _unreachable(self, exc: httpx.HTTPError) -> str:
        """Why stage 2 never answered, in the one line the operator reads.

        A refused connection to the small brain on a box with no model files is
        not an outage but a missing install, so it names the installer; a brain
        that is installed and merely down keeps today's plain unreachable text.
        """
        if (
            isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
            and self.uses_small_brain
            and not config.small_brain_ready()
        ):
            return NOT_INSTALLED
        return f"structuring server unreachable: {exc}"

    def _result(self, content: str) -> dict[str, Any]:
        """Extracted JSON through the contract: the check that it is a result."""
        data = extract_json(content)
        if not data.keys() & _RESULT_FIELDS:
            raise UnreadableError("model output has none of the contract fields")
        try:
            result = contract.Result.parse(data)
        except ValidationError as exc:
            raise UnreadableError(f"model output is not contract-valid: {exc}") from exc
        return result.model_dump()


def extract_json(content: str) -> dict[str, Any]:
    """The contract object inside a model's answer, repaired where models slip."""
    body = _TAGS_RE.sub("", content)
    fenced = _FENCE_RE.findall(body)
    # A model that shows an example and then the answer puts the answer last.
    for candidate in ([fenced[-1]] if fenced else []) + [body]:
        found = _first_object(candidate)
        if found is not None:
            return found
    raise UnreadableError("model output carries no JSON object")


def _first_object(text: str) -> dict[str, Any] | None:
    """First decodable JSON object in a noisy string, trailing commas mended.

    Each brace opens its own attempt, so a stray ``{...}`` in the surrounding
    chatter or a sentence after the object costs nothing.
    """
    decoder = json.JSONDecoder()
    for start in (index for index, char in enumerate(text) if char == "{"):
        tail = text[start:]
        for attempt in (tail, _TRAILING_COMMA_RE.sub(r"\1", tail)):
            try:
                value, _ = decoder.raw_decode(attempt)
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
    return None
