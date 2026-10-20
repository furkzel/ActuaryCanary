"""Day arithmetic against the standard library."""

from datetime import date, timedelta

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from actuarycanary.synthetic.days import (
    add_months,
    from_day,
    month_end,
    month_index,
    to_day,
    year_of,
)

dates = st.dates(min_value=date(2000, 1, 1), max_value=date(2040, 12, 31))


@given(dates)
def test_day_numbers_round_trip(d):
    assert from_day(to_day(d)) == d


@given(dates)
def test_month_end_is_the_last_day_of_the_month(d):
    last = from_day(int(month_end(month_index(to_day(d)))))
    assert (last.year, last.month) == (d.year, d.month)
    assert (last + timedelta(days=1)).month != d.month


@given(dates)
def test_year_of_matches_the_calendar(d):
    assert int(year_of(to_day(d))) == d.year


@given(dates, st.integers(1, 36))
def test_adding_months_keeps_the_day_or_the_last_day_of_a_shorter_month(d, k):
    moved = from_day(int(add_months(np.array([to_day(d)]), k)[0]))
    total = d.year * 12 + d.month - 1 + k
    assert (moved.year, moved.month) == (total // 12, total % 12 + 1)
    assert moved.day == d.day or (moved + timedelta(days=1)).month != moved.month


def test_a_policy_from_leap_day_ends_on_the_last_day_of_february():
    start = np.array([to_day(date(2024, 2, 29))])
    assert from_day(int(add_months(start, 12)[0])) == date(2025, 2, 28)
