"""CV02 inflation adjustment: restatement factors to a value date, missing months."""

from datetime import date

import polars as pl
import pytest

from actuarycanary.convert.inflation import FLAG_EARLIER_MONTH, restatement_factors
from actuarycanary.convert.market import ConversionError
from actuarycanary.structures.periods import month_index
from tests.convert.fixtures import MARKET_ROWS, market


def _factors(value_date: date, months: list[date], rows: list | None = None) -> dict:
    series = pl.Series([month_index(m) for m in months], dtype=pl.Int64)
    found = restatement_factors(market(rows or MARKET_ROWS), "CPI_TR", value_date, series)
    return {row["month"]: (row["factor"], row["flag"]) for row in found.iter_rows(named=True)}


def test_cv02_factor_is_the_index_of_the_value_date_over_the_index_of_the_month() -> None:
    months = [date(2024, 1, 15), date(2024, 2, 1), date(2024, 3, 31)]
    factors = _factors(date(2024, 3, 31), months)
    assert factors[month_index(months[0])] == (pytest.approx(1.32), "")
    assert factors[month_index(months[1])] == (pytest.approx(1.2), "")
    assert factors[month_index(months[2])] == (pytest.approx(1.0), "")


def test_cv02_a_different_value_date_changes_the_base() -> None:
    factors = _factors(date(2024, 2, 10), [date(2024, 1, 1), date(2024, 3, 1)])
    assert factors[month_index(date(2024, 1, 1))][0] == pytest.approx(1.1)
    assert factors[month_index(date(2024, 3, 1))][0] == pytest.approx(110 / 132)  # deflation


def test_cv02_a_missing_month_takes_the_latest_earlier_month_and_is_flagged() -> None:
    rows = [r for r in MARKET_ROWS if r[1] == "PRICE_INDEX" and r[2] != date(2024, 2, 29)]
    factors = _factors(date(2024, 3, 31), [date(2024, 2, 10)], rows)
    assert factors[month_index(date(2024, 2, 10))] == (pytest.approx(1.32), FLAG_EARLIER_MONTH)


def test_cv02_a_month_before_the_series_cannot_be_restated() -> None:
    factors = _factors(date(2024, 3, 31), [date(2023, 12, 31)])
    assert factors[month_index(date(2023, 12, 31))] == (None, "")


def test_cv02_the_series_and_the_value_date_must_exist() -> None:
    series = pl.Series([month_index(date(2024, 1, 1))], dtype=pl.Int64)
    with pytest.raises(ConversionError, match="no PRICE_INDEX series NOPE"):
        restatement_factors(market(), "NOPE", date(2024, 3, 31), series)
    with pytest.raises(ConversionError, match="no value on or before"):
        restatement_factors(market(), "CPI_TR", date(2023, 12, 31), series)
