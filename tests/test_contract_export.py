"""T04: committed schema and CONTRACT.md stay in lockstep with app/contract.py."""
import json

import jsonschema
import pytest

from app import config, contract
from scripts import gen_contract_doc

ROOT = config.ROOT
DOC_FILE = ROOT / "CONTRACT.md"
FIXTURES = sorted((ROOT / "fixtures").glob("*.json"))

_DOC_MODELS = (
    contract.JobEnvelope,
    contract.Result,
    contract.Header,
    contract.ReceiptMeta,
    contract.Item,
    contract.Totals,
    contract.Validation,
    contract.TotalsBlock,
    contract.JobMeta,
)


def _result_schema() -> dict:
    schema = json.loads(contract.SCHEMA_PATH.read_text(encoding="utf-8"))
    return {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/Result"}


def test_fixtures_present():
    assert FIXTURES


def test_committed_schema_is_byte_stable_regeneration():
    assert contract.SCHEMA_PATH.read_text(encoding="utf-8") == contract.schema_text()


def test_schema_text_is_deterministic():
    assert contract.schema_text() == contract.schema_text()


def test_regeneration_rewrites_identical_bytes():
    paths = (contract.SCHEMA_PATH, DOC_FILE)
    before = [p.read_bytes() for p in paths]
    gen_contract_doc.main()
    assert [p.read_bytes() for p in paths] == before


def test_schema_root_is_job_envelope():
    schema = json.loads(contract.SCHEMA_PATH.read_text(encoding="utf-8"))
    # sort_keys in schema_text, so compare as a set, not declaration order.
    assert set(schema["properties"]) == {
        "job_id",
        "status",
        "client_ref",
        "result",
        "validation",
        "meta",
    }
    assert "Result" in schema["$defs"]


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_fixture_parses_as_valid_result(fixture):
    data = json.loads(fixture.read_text(encoding="utf-8"))
    result = contract.Result.parse(data)
    assert result.para_birimi == "TRY"
    assert result.items
    jsonschema.validate(data, _result_schema())


def test_doc_tables_cover_every_contract_field():
    doc = DOC_FILE.read_text(encoding="utf-8")
    for model in _DOC_MODELS:
        for name in model.model_fields:
            assert f"| `{name}` |" in doc, f"{model.__name__}.{name} missing from CONTRACT.md"


def test_doc_covers_verdicts_endpoints_and_versioning():
    doc = DOC_FILE.read_text(encoding="utf-8")
    for token in (
        "`ok`",
        "`mismatch`",
        "`unreadable`",
        "POST | `/v1/jobs`",
        "GET | `/v1/jobs/{id}`",
        "PATCH | `/v1/jobs/{id}`",
        "`/v1/` is frozen",
        "`/v2/`",
    ):
        assert token in doc
