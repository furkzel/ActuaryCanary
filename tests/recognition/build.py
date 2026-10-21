"""Tiny raw tables built in code, as the reader would return them."""

from typing import Any

import polars as pl

from actuarycanary.io.excel import SOURCE_FILE, SOURCE_ROW, SOURCE_SHEET, RawTable
from actuarycanary.recognition.dictionary import build_dictionary
from actuarycanary.spec.loader import load_specs

SPECS = load_specs()
DICTIONARY = build_dictionary(SPECS)


def table(columns: dict[str, list[Any]], sheet: str = "Sheet1", header_row: int = 1) -> RawTable:
    n = len(next(iter(columns.values())))
    frame = pl.DataFrame(columns, strict=False).with_columns(
        pl.lit("input.xlsx").alias(SOURCE_FILE),
        pl.lit(sheet).alias(SOURCE_SHEET),
        pl.Series(SOURCE_ROW, range(header_row + 1, header_row + 1 + n), dtype=pl.Int64),
    )
    return RawTable(sheet, frame, header_row)


def valuations(**renamed: str) -> dict[str, list[Any]]:
    """Four claim valuation rows; keyword arguments rename canonical columns."""
    columns: dict[str, list[Any]] = {
        "claim_id": ["0001", "0001", "0002", "0003"],
        "valuation_date": ["2024-01-31", "29.02.2024", "2024-02-29", "31.03.2024"],
        "paid_to_date": [0.0, 100.0, 50.0, 0.0],
        "case_reserve": [500.0, 400.0, 0.0, 70.0],
        "status": ["AÇIK", "Devam Ediyor", "KAPANDI", "Davalı"],
        "currency": ["TRY", "TRY", "USD", "TRY"],
    }
    return {renamed.get(k, k): v for k, v in columns.items()}
