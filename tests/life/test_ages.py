"""Ages and policy years by anniversaries (CV11, record 0445), on hand cases."""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.life.ages import (
    attained_age,
    band_expr,
    entry_age,
    jan1,
    policy_year,
    shift_years,
    to_days,
    whole_years,
    year_of,
)


def days(*dates: date) -> np.ndarray:
    return to_days(pl.Series(list(dates)))


def test_an_anniversary_inside_a_calendar_year_moves_age_and_policy_year_together() -> None:
    entry = days(date(2018, 7, 15))
    # first valuation 2020-12-31 says 47: two anniversaries passed, so the entry age is 45
    a_e = entry_age(entry, days(date(2020, 12, 31)), np.array([47]))
    assert a_e.tolist() == [45]
    before, after = days(date(2023, 7, 14)), days(date(2023, 7, 15))
    assert attained_age(entry, a_e, before).tolist() == [49]
    assert attained_age(entry, a_e, after).tolist() == [50]
    assert policy_year(entry, before).tolist() == [5] and policy_year(entry, after).tolist() == [6]


def test_a_first_valuation_years_after_entry() -> None:
    entry = days(date(2005, 3, 1))
    a_e = entry_age(entry, days(date(2022, 12, 31)), np.array([60]))
    assert a_e.tolist() == [43]  # 17 whole years from entry to the first valuation
    assert policy_year(entry, days(date(2005, 3, 1))).tolist() == [1]  # the entry day itself


def test_a_band_source_uses_its_lower_age() -> None:
    """A band "45-49" at the first valuation is read as 45 for the arithmetic (CV11)."""
    entry = days(date(2021, 2, 1))
    assert entry_age(entry, days(date(2022, 12, 31)), np.array([45])).tolist() == [44]


def test_29_february_has_its_anniversary_on_28_february() -> None:
    entry = days(date(2020, 2, 29))
    assert shift_years(entry, 1).tolist() == days(date(2021, 2, 28)).tolist()
    assert shift_years(entry, 4).tolist() == days(date(2024, 2, 29)).tolist()
    assert whole_years(entry, days(date(2021, 2, 27))).tolist() == [0]
    assert whole_years(entry, days(date(2021, 2, 28))).tolist() == [1]


def test_years_and_first_of_january() -> None:
    assert year_of(days(date(1999, 12, 31), date(2000, 1, 1))).tolist() == [1999, 2000]
    assert jan1(np.array([2024])).tolist() == days(date(2024, 1, 1)).tolist()


@pytest.mark.parametrize(
    ("age", "width", "source_width", "open_band", "label"),
    [
        (47, 5, 1, False, "45-49"),
        (47, 1, 1, False, "47"),
        (47, 5, 5, False, "45-49"),  # a band of the report's width follows the age
        (50, 5, 10, False, "50-59"),  # a wider source band keeps its width, moved with time
        (87, 5, 1, True, "87+"),  # an open band stays open
        (40, 10, 1, False, "40-49"),
    ],
)
def test_the_age_band_of_the_outputs(age, width, source_width, open_band, label) -> None:
    frame = pl.DataFrame({"age": [age], "w": [source_width], "o": [open_band]})
    got = frame.select(band_expr(pl.col("age"), width, pl.col("w"), pl.col("o")))
    assert got.item() == label
