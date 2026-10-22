"""Frames built in code for the quality tests."""

from calendar import monthrange
from datetime import date
from typing import Any

import polars as pl

from actuarycanary.io.excel import SOURCE_FILE, SOURCE_ROW, SOURCE_SHEET
from actuarycanary.spec.loader import load_specs

SPECS = load_specs().data
TYPES = {"text": pl.String, "date": pl.Date, "number": pl.Float64}
Rows = dict[str, list[dict[str, Any]]]


def frames(rows: Rows) -> dict[str, pl.DataFrame]:
    result = {}
    for concept, items in rows.items():
        kinds = {f.name: TYPES[f.type] for f in SPECS[concept].fields}
        names = list(dict.fromkeys(k for item in items for k in item))
        data = {n: [item.get(n) for item in items] for n in names}
        frame = pl.DataFrame(data, schema={n: kinds[n] for n in names})
        result[concept] = frame.with_columns(
            pl.lit("f.xlsx").alias(SOURCE_FILE),
            pl.lit("s").alias(SOURCE_SHEET),
            (pl.int_range(pl.len()) + 2).cast(pl.Int64).alias(SOURCE_ROW),
        )
    return result


def cv(month: int = 1, **values: Any) -> dict[str, Any]:
    base = {
        "claim_id": "1",
        "valuation_date": date(2024, month, monthrange(2024, month)[1]),
        "paid_to_date": 0.0,
        "case_reserve": 10.0,
        "status": "OPEN",
        "currency": "TRY",
    }
    return {**base, **values}


def claim(**values: Any) -> dict[str, Any]:
    base = {
        "claim_id": "1",
        "occurrence_date": date(2024, 1, 10),
        "report_date": date(2024, 1, 12),
        "close_date": date(2024, 3, 1),
    }
    return {**base, **values}


def policy(**values: Any) -> dict[str, Any]:
    base = {
        "policy_id": "P1",
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 12, 31),
        "segment": "LIFE",
        "line": "X",
        "currency": "TRY",
    }
    return {**base, **values}


def premium(**values: Any) -> dict[str, Any]:
    base = {
        "transaction_id": "T1",
        "policy_id": "P1",
        "booking_date": date(2024, 1, 5),
        "amount": 5.0,
        "currency": "TRY",
        "type": "WRITTEN",
    }
    return {**base, **values}


def expense(**values: Any) -> dict[str, Any]:
    base = {"period": date(2024, 1, 31), "amount": 5.0, "type": "OTHER", "currency": "TRY"}
    return {**base, **values}


def series(**values: Any) -> dict[str, Any]:
    base = {"series_id": "USD", "kind": "FX_SPOT", "date": date(2024, 1, 31), "value": 30.0}
    return {**base, **values}
