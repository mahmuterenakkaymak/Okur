# Contract v1

Machine-readable source of truth: `app/contract.py` (pydantic).
`contract/contract_v1.schema.json` is exported from it (JSON Schema draft
2020-12, root = job envelope). Regenerate both artifacts with
`python scripts/gen_contract_doc.py`.

## Versioning — `/v1/` is frozen

Breaking changes never land in `/v1/`. Adding a field is allowed (consumers
must ignore unknown fields); renaming, removing or re-typing a field is
breaking and ships as `/v2/`.

## Defaults

A missing field never arrives as null: strings are `""`, numbers `0.0`,
arrays `[]`, `para_birimi` `"TRY"`, `quality_mode` `false`, `client_ref`
`null`. Amounts may arrive in the forms a Turkish receipt prints
(`1.046,40`, `%20`, `198,82 TL`); the contract normalizes them to plain
numbers before anyone downstream sees them.

## Endpoints

All `/v1` routes require the `X-API-Key` header.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/v1/jobs` | Submit a receipt: multipart `image`, optional `mode`, `client_ref`, `captured_at`. New job → `202 {job_id}`; a repeated `client_ref` for the same key → `200` with the existing `job_id`, no re-queue. |
| GET | `/v1/jobs/{id}` | The job envelope below. |
| GET | `/v1/jobs` | List jobs; filters `status`, `worker`, `since`, `mine`. |
| PATCH | `/v1/jobs/{id}` | Admin field correction; re-runs the validator. |
| POST | `/v1/jobs/{id}/rerun` | Quality-mode rerun against the stronger model; replaces result and meta. |
| GET | `/v1/export` | `format=json` / `csv` / `xlsx`; filters `ids`, `worker`, `since`. |
| GET | `/v1/status` | Service health, VRAM and queue depth. |


## Job envelope — response root

Every `/v1` job response carries this envelope. `result` and `validation` are `null` until the job reaches `done`.

| Field | Type | Default |
| --- | --- | --- |
| `job_id` | `str` | `""` |
| `status` | `queued \| running \| done \| failed` | `"queued"` |
| `client_ref` | `str \| null` | `null` |
| `result` | `Result \| null` | `null` |
| `validation` | `Validation \| null` | `null` |
| `meta` | `JobMeta` | `{}` |

## `result`

The structured receipt. Field names are Turkish because they are the receipt's own terms.

| Field | Type | Default |
| --- | --- | --- |
| `header` | `Header` | `{}` |
| `meta` | `ReceiptMeta` | `{}` |
| `items` | `Item[]` | `[]` |
| `totals` | `Totals` | `{}` |
| `para_birimi` | `str` | `"TRY"` |
| `okunamayan` | `str[]` | `[]` |

## `result.header`

Firm info as printed on the receipt.

| Field | Type | Default |
| --- | --- | --- |
| `isim` | `str` | `""` |
| `vergi_dairesi` | `str` | `""` |
| `vergi_no` | `str` | `""` |

## `result.meta`

Receipt number/date line; `tarih` is `dd.MM.yyyy`, `saat` is `HH:mm`.

| Field | Type | Default |
| --- | --- | --- |
| `tarih` | `str` | `""` |
| `saat` | `str` | `""` |
| `no` | `str` | `""` |
| `tip` | `str` | `""` |

## `result.items[]`

One product line; `miktar` carries kg quantities to three decimals.

| Field | Type | Default |
| --- | --- | --- |
| `ad` | `str` | `""` |
| `miktar` | `float` | `0.0` |
| `birim_fiyat` | `float` | `0.0` |
| `toplam` | `float` | `0.0` |

## `result.totals`

Amounts as the model read them; the validator recomputes them, never the other way round.

| Field | Type | Default |
| --- | --- | --- |
| `ara_toplam` | `float` | `0.0` |
| `iskonto` | `float` | `0.0` |
| `kdv` | `float` | `0.0` |
| `kdv_orani` | `float` | `0.0` |
| `toplam` | `float` | `0.0` |

## `validation`

Deterministic verdict block; see Verdicts below.

| Field | Type | Default |
| --- | --- | --- |
| `verdict` | `ok \| mismatch \| unreadable` | `"unreadable"` |
| `expected` | `TotalsBlock` | `{}` |
| `actual` | `TotalsBlock` | `{}` |
| `fields` | `str[]` | `[]` |

## `validation.expected` / `validation.actual`

The four amounts the validator recomputes (expected) versus what the model printed (actual).

| Field | Type | Default |
| --- | --- | --- |
| `ara_toplam` | `float` | `0.0` |
| `iskonto` | `float` | `0.0` |
| `kdv` | `float` | `0.0` |
| `toplam` | `float` | `0.0` |

## `meta`

Provenance and timings.

| Field | Type | Default |
| --- | --- | --- |
| `worker` | `str` | `""` |
| `captured_at` | `str \| null` | `null` |
| `received_at` | `str` | `""` |
| `ocr_ms` | `int` | `0` |
| `total_ms` | `int` | `0` |
| `model` | `str` | `""` |
| `quality_mode` | `bool` | `false` |

## Verdicts

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
