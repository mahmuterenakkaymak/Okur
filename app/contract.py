"""Contract v1 shapes: result, validation block and job envelope.

Every field carries the house default from PLAN.md "Contracts" (strings "",
numbers 0.0, arrays [], para_birimi TRY, quality_mode False, client_ref None),
so partial model output or a thin queue row parses into a whole object and no
view, export or total has to guard against null. Amounts arrive in the forms a
receipt prints, so they go through the one shared parser in app.numbers; a
value that cannot be read lands on 0.0 and the validator reports the
discrepancy rather than the contract guessing.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from app import config, numbers

_STATUS = Literal["queued", "running", "done", "failed"]
_VERDICT = Literal["ok", "mismatch", "unreadable"]


def _lowered(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


def _to_text(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, int):  # vergi_no arrives as a bare number
        return str(value)
    return value


def _to_amount(value: object) -> object:
    # ASSUMPTION: the contract, not stage 2, normalizes printed forms, so every
    # consumer downstream (validator, exports, views) sees plain floats.
    number = numbers.parse_number(value)
    return 0.0 if number is None else number


def _to_rate(value: object) -> object:
    rate = numbers.parse_percent(value)
    return 0.0 if rate is None else rate


Status = Annotated[_STATUS, BeforeValidator(_lowered)]
Verdict = Annotated[_VERDICT, BeforeValidator(_lowered)]
Text = Annotated[str, BeforeValidator(_to_text)]
Amount = Annotated[float, BeforeValidator(_to_amount)]
Rate = Annotated[float, BeforeValidator(_to_rate)]


class _Model(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _null_is_missing(cls, data: Any) -> Any:
        """One rule for every field: null means absent, so the default wins.

        Safe because each genuinely-nullable field (client_ref, captured_at,
        result, validation) defaults to None anyway.
        """
        if isinstance(data, Mapping):
            return {key: value for key, value in data.items() if value is not None}
        return data

    @classmethod
    def parse(cls, data: Mapping[str, Any] | None) -> Self:
        """Whole object from partial data; a non-contract shape still raises."""
        return cls.model_validate(dict(data) if data is not None else {})


class Header(_Model):
    isim: Text = ""
    vergi_dairesi: Text = ""
    vergi_no: Text = ""


class ReceiptMeta(_Model):
    tarih: Text = ""
    saat: Text = ""
    no: Text = ""
    tip: Text = ""


class Item(_Model):
    ad: Text = ""
    miktar: Amount = 0.0
    birim_fiyat: Amount = 0.0
    toplam: Amount = 0.0


class Totals(_Model):
    ara_toplam: Amount = 0.0
    iskonto: Amount = 0.0
    kdv: Amount = 0.0
    kdv_orani: Rate = 0.0
    toplam: Amount = 0.0


class Result(_Model):
    header: Header = Field(default_factory=Header)
    meta: ReceiptMeta = Field(default_factory=ReceiptMeta)
    items: list[Item] = Field(default_factory=list)
    totals: Totals = Field(default_factory=Totals)
    para_birimi: Text = config.CURRENCY
    okunamayan: list[Text] = Field(default_factory=list)


class TotalsBlock(_Model):
    """The four amounts the validator recomputes, used for expected and actual."""

    ara_toplam: Amount = 0.0
    iskonto: Amount = 0.0
    kdv: Amount = 0.0
    toplam: Amount = 0.0


class Validation(_Model):
    # ASSUMPTION: a missing verdict is unreadable, never an implied ok.
    verdict: Verdict = "unreadable"
    expected: TotalsBlock = Field(default_factory=TotalsBlock)
    actual: TotalsBlock = Field(default_factory=TotalsBlock)
    fields: list[Text] = Field(default_factory=list)


class JobMeta(_Model):
    worker: Text = ""
    captured_at: str | None = None
    received_at: Text = ""
    ocr_ms: int = 0
    total_ms: int = 0
    model: Text = ""
    quality_mode: bool = False


class JobEnvelope(_Model):
    job_id: Text = ""
    status: Status = "queued"
    client_ref: str | None = None
    result: Result | None = None
    validation: Validation | None = None
    meta: JobMeta = Field(default_factory=JobMeta)
