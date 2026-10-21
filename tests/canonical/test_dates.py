"""Dates given as text (records 0017 and 0027): formats found per column, then parsed."""

from datetime import date, datetime

import polars as pl

from actuarycanary.canonical.dates import parse_dates
from actuarycanary.canonical.feeds import as_text


def test_mixed_real_and_text_dates_parse_to_the_same_dates() -> None:
    series = pl.Series(
        "d", ["2022-01-31 00:00:00", "28.02.2022", "2022-03-31", "30/04/2022", None, "nope"]
    )
    parsed = parse_dates(series)
    assert parsed.values.to_list() == [
        date(2022, 1, 31),
        date(2022, 2, 28),
        date(2022, 3, 31),
        date(2022, 4, 30),
        None,
        None,
    ]
    assert "%d.%m.%Y" in parsed.formats and "%d/%m/%Y" in parsed.formats


def test_month_first_is_found_from_the_values() -> None:
    parsed = parse_dates(pl.Series("d", ["01/31/2022", "02/28/2022"]))
    assert parsed.values.to_list() == [date(2022, 1, 31), date(2022, 2, 28)]
    assert parsed.note.startswith("month first")


def test_undecided_order_is_day_first_and_says_so() -> None:
    parsed = parse_dates(pl.Series("d", ["01/02/2022", "03/04/2022"]))
    assert parsed.values.to_list() == [date(2022, 2, 1), date(2022, 4, 3)]
    assert "day first assumed" in parsed.note


def test_typed_dates_pass_and_other_types_are_empty() -> None:
    assert parse_dates(pl.Series("d", [date(2024, 1, 31)])).values.to_list() == [date(2024, 1, 31)]
    stamped = parse_dates(pl.Series("d", [datetime(2024, 1, 31, 13, 5)]))
    assert stamped.values.to_list() == [date(2024, 1, 31)]
    assert parse_dates(pl.Series("d", [45322.0])).values.to_list() == [None]


def test_whole_numbers_read_as_text_keep_no_decimal_part() -> None:
    assert as_text(pl.Series([1.0, None, 271.0])).to_list() == ["1", None, "271"]
    assert as_text(pl.Series([1.5, 2.0])).to_list() == ["1.5", "2.0"]
