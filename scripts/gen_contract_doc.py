"""Regenerate the committed contract artifacts from app/contract.py.

    python scripts/gen_contract_doc.py

Writes contract/contract_v1.schema.json and CONTRACT.md. Both are byte-stable:
rerunning with unchanged models rewrites identical bytes, so the committed
files are the regeneration check.
"""
from __future__ import annotations

import json
import pathlib
import sys

if not __package__:  # direct `python scripts/gen_contract_doc.py` from the root
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import config, contract

DOC_PATH = config.ROOT / "CONTRACT.md"

_TYPE_NAMES = {"string": "str", "number": "float", "integer": "int", "boolean": "bool", "null": "null"}

# ASSUMPTION: the endpoint table lists only shipped doors, while the versioning
# note keeps naming the absent /v1 correction row — integrators coming from the
# old doc must see that door was never registered, not that it moved silently.
_HEADER = """# Contract v1

Machine-readable source of truth: `app/contract.py` (pydantic).
`contract/contract_v1.schema.json` is exported from it (JSON Schema draft
2020-12, root = job envelope). Regenerate both artifacts with
`python scripts/gen_contract_doc.py`.

## Versioning — `/v1/` is frozen

Breaking changes never land in `/v1/`. Adding a field is allowed (consumers
must ignore unknown fields); renaming, removing or re-typing a field is
breaking and ships as `/v2/`.

Corrections are not a `/v1` door at all: the table below has no
``PATCH | `/v1/jobs/{id}` `` row, and the admin door is the only way to
correct a stored receipt.

## Defaults

A missing field never arrives as null: strings are `""`, numbers `0.0`,
arrays `[]`, `para_birimi` `"TRY"`, `quality_mode` `false`, `client_ref`
`null`. Amounts may arrive in the forms a Turkish receipt prints
(`1.046,40`, `%20`, `198,82 TL`); the contract normalizes them to plain
numbers before anyone downstream sees them.

## Endpoints

All `/v1` routes require the `X-API-Key` header. The review doors below ship
under `/admin/api` on the admin session cookie instead — POST
`/admin/api/login` exchanges the server's `ADMIN_TOKEN` for it — because `/v1`
is key-authed per integrator, while corrections, exports and health read every
worker's receipts.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/v1/jobs` | Submit a receipt: multipart `image`, optional `mode`, `client_ref`, `captured_at`. New job → `202 {job_id}`; a repeated `client_ref` for the same key → `200` with the existing `job_id`, no re-queue. |
| GET | `/v1/jobs/{id}` | The job envelope below. |
| GET | `/v1/jobs` | List jobs; filters `status`, `worker`, `since`, `mine`. |
| PATCH | `/admin/api/jobs/{id}` | Admin field correction; re-runs the validator. |
| POST | `/admin/api/jobs/{id}/rerun` | Quality-mode rerun against the stronger model; replaces result and meta. |
| GET | `/admin/api/export` | `format=json` / `csv` / `xlsx`; filters `ids`, `worker`, `since`. |
| GET | `/admin/api/status` | Service health, VRAM and queue depth. |
"""

_VERDICTS = """## Verdicts

`validation.verdict` is one of:

| Verdict | Meaning |
| --- | --- |
| `ok` | The validator recomputed the totals from `items[]` and they match the model output within 0.01; `fields` is `[]`. |
| `mismatch` | At least one amount disagrees; `fields` lists the dotted paths of the offenders (`items[2].toplam`, `totals.kdv`). |
| `unreadable` | The model could not produce schema-valid JSON; `result` may be partial and `okunamayan` lists the fragments it could not read. |

The LLM never owns a number: `validation.expected` is always recomputed from
`items[]` by the validator, `actual` is what the model printed. Corrections
and quality-mode reruns re-run the validator, so the verdict always reflects
the currently stored data.
"""

# (heading, model, intro) in reading order; tables derive from the models.
_SECTIONS: list[tuple[str, type, str]] = [
    ("Job envelope — response root", contract.JobEnvelope,
     "Every `/v1` job response carries this envelope. `result` and `validation` "
     "are `null` until the job reaches `done`."),
    ("`result`", contract.Result,
     "The structured receipt. Field names are Turkish because they are the "
     "receipt's own terms."),
    ("`result.header`", contract.Header, "Firm info as printed on the receipt."),
    ("`result.meta`", contract.ReceiptMeta,
     "Receipt number/date line; `tarih` is `dd.MM.yyyy`, `saat` is `HH:mm`."),
    ("`result.items[]`", contract.Item,
     "One product line; `miktar` carries kg quantities to three decimals."),
    ("`result.totals`", contract.Totals,
     "Amounts as the model read them; the validator recomputes them, never "
     "the other way round."),
    ("`validation`", contract.Validation,
     "Deterministic verdict block; see Verdicts below."),
    ("`validation.expected` / `validation.actual`", contract.TotalsBlock,
     "The four amounts the validator recomputes (expected) versus what the "
     "model printed (actual)."),
    ("`meta`", contract.JobMeta, "Provenance and timings."),
    ("`meta.stage_ms`", contract.StageMs,
     "Milliseconds per stage; a stage that never ran reads 0. `total_ms` is the "
     "whole run, so it is never the sum of these three. On a `failed` job the "
     "stage that died reports the wait it waited and every stage past it is 0 — "
     "the breakdown names the stage that died."),
]


def _type_name(node: dict) -> str:
    # "\\|" keeps the pipe from splitting the markdown table cell.
    if "enum" in node:
        return " \\| ".join(node["enum"])
    if "$ref" in node:
        return node["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in node:
        return " \\| ".join(_type_name(part) for part in node["anyOf"])
    if node.get("type") == "array":
        return _type_name(node["items"]) + "[]"
    return _TYPE_NAMES.get(node.get("type"), "any")


def _default(model: type, name: str, type_name: str) -> str:
    field = model.model_fields[name]
    if field.default_factory is not None:
        return "`[]`" if type_name.endswith("[]") else "`{}`"
    return f"`{json.dumps(field.default, ensure_ascii=False)}`"


def _table(model: type, node: dict) -> str:
    lines = ["| Field | Type | Default |", "| --- | --- | --- |"]
    for name, prop in node["properties"].items():
        type_name = _type_name(prop)
        lines.append(
            f"| `{name}` | `{type_name}` | {_default(model, name, type_name)} |"
        )
    return "\n".join(lines)


def doc_text() -> str:
    schema = contract.JobEnvelope.model_json_schema()
    parts = [_HEADER]
    for heading, model, intro in _SECTIONS:
        node = schema if model is contract.JobEnvelope else schema["$defs"][model.__name__]
        parts.append(f"## {heading}\n\n{intro}\n\n{_table(model, node)}")
    parts.append(_VERDICTS)
    return "\n\n".join(parts).rstrip() + "\n"


def _write(path: pathlib.Path, text: str) -> None:
    # newline="\n": identical bytes on Windows and Linux.
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    contract.SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write(contract.SCHEMA_PATH, contract.schema_text())
    _write(DOC_PATH, doc_text())
    print(f"wrote {contract.SCHEMA_PATH}")
    print(f"wrote {DOC_PATH}")


if __name__ == "__main__":
    main()
