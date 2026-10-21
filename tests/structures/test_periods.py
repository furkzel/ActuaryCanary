"""CV04 periods, month indices and labels."""

from datetime import date

from actuarycanary.structures.periods import (
    Period,
    month_end,
    month_index,
    period_label,
    period_start,
)


def test_month_index_and_month_end() -> None:
    assert month_index(date(2024, 2, 10)) == 12 * 2024 + 1
    assert month_end(month_index(date(2024, 2, 10))) == date(2024, 2, 29)


def test_labels_on_the_calendar_year() -> None:
    m = month_index(date(2025, 8, 15))
    assert period_label(period_start(m, Period.YEAR), Period.YEAR) == "2025"
    assert period_label(period_start(m, Period.HALF), Period.HALF) == "2025-H2"
    assert period_label(period_start(m, Period.QUARTER), Period.QUARTER) == "2025-Q3"
    assert period_label(period_start(m, Period.MONTH), Period.MONTH) == "2025-08"


def test_labels_on_a_fiscal_year_starting_in_april() -> None:
    m = month_index(date(2026, 2, 1))  # February 2026 lies in the fiscal year from April 2025
    start = period_start(m, Period.YEAR, fiscal_start=4)
    assert month_end(start) == date(2025, 4, 30)
    assert period_label(start, Period.YEAR, fiscal_start=4) == "2025"
    quarter = period_start(m, Period.QUARTER, fiscal_start=4)
    assert period_label(quarter, Period.QUARTER, fiscal_start=4) == "2025-Q4"
