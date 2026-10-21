"""Canonical feeds: spec types and the row rules of claim_valuations and claims."""

from datetime import date
from typing import Any

import polars as pl
import pytest

from actuarycanary.canonical.feeds import (
    UNKNOWN,
    UNMAPPED,
    CanonicalError,
    CanonicalFeed,
    canonicalise,
)
from actuarycanary.io.excel import SOURCE_FILE, SOURCE_ROW, SOURCE_SHEET, RawTable
from actuarycanary.spec.loader import load_specs

SPECS = load_specs()


def _table(rows: list[dict[str, Any]], name: str) -> RawTable:
    frame = pl.DataFrame(rows, infer_schema_length=None).with_columns(
        pl.lit(f"{name}.xlsx").alias(SOURCE_FILE),
        pl.lit(name).alias(SOURCE_SHEET),
        pl.Series(SOURCE_ROW, range(2, len(rows) + 2), dtype=pl.Int64),
    )
    return RawTable(name, frame)


def _valuation(claim: str | None, day: date | None, **values: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "claim_id": claim,
        "valuation_date": day,
        "paid_to_date": 10.0,
        "case_reserve": 5.0,
        "status": "OPEN",
        "currency": "TRY",
    }
    return row | values


def _valuations(*rows: dict[str, Any]) -> CanonicalFeed:
    return canonicalise(_table(list(rows), "claim_valuations"), SPECS.data["claim_valuations"])


def _rules(feed: CanonicalFeed) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in feed.findings:
        counts[f.rule] = counts.get(f.rule, 0) + f.count
    return counts


def test_required_column_missing_is_rejected() -> None:
    table = _table([{"claim_id": "1", "valuation_date": date(2024, 1, 31)}], "claim_valuations")
    with pytest.raises(CanonicalError, match="paid_to_date"):
        canonicalise(table, SPECS.data["claim_valuations"])


def test_types_follow_the_spec_and_failed_casts_are_listed() -> None:
    feed = _valuations(
        _valuation(" 007 ", date(2024, 1, 31)),
        _valuation("8", date(2024, 1, 31), paid_to_date="abc"),
    )
    assert feed.frame.schema["claim_id"] == pl.String
    assert feed.frame.schema["paid_to_date"] == pl.Float64
    assert feed.frame["claim_id"].to_list() == ["007", "8"]  # trimmed, leading zeros kept
    assert feed.frame["paid_to_date"].to_list() == [10.0, None]
    assert _rules(feed)["CV07"] == 1
    assert "subrogation_to_date" not in feed.fields  # an absent optional field stays absent


def test_dv_clv_01_rows_without_keys_are_excluded() -> None:
    feed = _valuations(_valuation(None, date(2024, 1, 31)), _valuation("1", None))
    assert feed.frame.height == 0
    assert _rules(feed)["DV-CLV-01"] == 2


def test_dv_clv_05_valuation_dates_move_to_the_month_end() -> None:
    feed = _valuations(_valuation("1", date(2024, 2, 10)))
    assert feed.frame["valuation_date"].to_list() == [date(2024, 2, 29)]
    assert _rules(feed)["DV-CLV-05"] == 1


def test_dv_clv_03_and_04_currency_and_status_classes() -> None:
    feed = _valuations(
        _valuation("1", date(2024, 1, 31), currency=None, status="PEND-REV"),
        _valuation("2", date(2024, 1, 31), currency="tl", status=None),
        _valuation("3", date(2024, 1, 31), status="CLOSED_NIL"),
    )
    assert feed.frame["currency"].to_list() == [UNKNOWN, UNKNOWN, "TRY"]
    assert feed.frame["status"].to_list() == [UNMAPPED, UNMAPPED, "CLOSED_NIL"]
    assert _rules(feed) == {"DV-CLV-03": 2, "DV-CLV-04": 2}


def test_dv_clv_02_empty_amounts_are_kept_and_listed() -> None:
    feed = _valuations(_valuation("1", date(2024, 1, 31), case_reserve=None))
    assert feed.frame.height == 1
    assert _rules(feed)["DV-CLV-02"] == 1


def test_dv_clv_06_identical_duplicates_kept_once() -> None:
    row = _valuation("1", date(2024, 1, 31))
    feed = _valuations(row, row, _valuation("1", date(2024, 2, 29)))
    assert feed.frame[SOURCE_ROW].to_list() == [2, 4]
    assert _rules(feed)["DV-CLV-06"] == 1


def test_dv_clv_06_conflicting_rows_keep_the_later_date_then_the_later_row() -> None:
    feed = _valuations(
        _valuation("1", date(2024, 1, 20), paid_to_date=1.0),
        _valuation("1", date(2024, 1, 31), paid_to_date=2.0),
        _valuation("1", date(2024, 1, 10), paid_to_date=3.0),
        _valuation("2", date(2024, 1, 31), paid_to_date=4.0),
        _valuation("2", date(2024, 1, 31), paid_to_date=5.0),
    )
    assert feed.frame["paid_to_date"].to_list() == [2.0, 5.0]
    assert _rules(feed)["DV-CLV-06"] == 3


def _claim(claim: str | None, **values: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "claim_id": claim,
        "occurrence_date": date(2024, 1, 5),
        "report_date": date(2024, 1, 9),
        "segment": "NON_LIFE",
        "line": "MOTOR_OD",
    }
    return row | values


def test_claims_rules_dv_clm_01_02_03_06() -> None:
    feed = canonicalise(
        _table(
            [
                _claim(None),
                _claim("1"),
                _claim("1"),
                _claim("1", line="PROPERTY"),
                _claim("2", segment=None, line=None),
                _claim("3", segment="Hayat dışı"),
            ],
            "claims",
        ),
        SPECS.data["claims"],
    )
    assert feed.frame["claim_id"].to_list() == ["1", "2", "3"]
    assert feed.frame["line"].to_list() == ["MOTOR_OD", UNKNOWN, "MOTOR_OD"]
    assert feed.frame["segment"].to_list() == ["NON_LIFE", UNKNOWN, UNMAPPED]
    rules = _rules(feed)
    assert rules["DV-CLM-01"] == 1
    assert rules["DV-CLM-02"] == 2  # one identical, one conflicting
    assert rules["DV-CLM-03"] == 2
    assert rules["DV-CLM-06"] == 1
