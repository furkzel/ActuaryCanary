"""EX04 Administration cost per policy: hand-computed fixtures of the specification."""

from datetime import date

import pytest

from actuarycanary.convert.bases import ValueBasis
from actuarycanary.structures.periods import Period
from tests.measures.helpers import make_inputs, measure, one, table
from tests.quality.builders import cv, expense, policy

JUNE = date(2024, 6, 30)
CUT_OFF = date(2024, 12, 31)


def admin(amount: float, period: date = JUNE, **more) -> dict:
    return expense(type="ADMINISTRATION", amount=amount, period=period, **more)


def cover(number: int, start: date, end: date, **more) -> dict:
    return policy(policy_id=f"P{number}", start_date=start, end_date=end, **more)


def inputs_of(expenses: list[dict], policies: list[dict], **extra):
    rows = {"claim_valuations": [cv(12)], "expenses": expenses, "policies": policies}
    return make_inputs(rows, cut_off=CUT_OFF, **extra)


def monthly(inputs, *breakdowns: str, **more):
    return measure(inputs, "EX04", *breakdowns, "calendar_period", period=Period.MONTH, **more)


def test_ex04_two_policies_in_force_for_half_a_month_each() -> None:
    """Two policies in force for half of a month each and an expense of 100: one policy on
    average, 100 per policy."""
    policies = [
        cover(1, date(2024, 6, 1), date(2024, 6, 16)),  # 15 of the 30 days of June
        cover(2, date(2024, 6, 16), date(2024, 7, 1)),  # the end date is exclusive
    ]
    result = monthly(inputs_of([admin(100.0)], policies))
    assert one(result) == pytest.approx(100.0)
    assert one(result, "numerator") == 100.0 and one(result, "denominator") == pytest.approx(1.0)


def test_ex04_cover_ends_at_the_cancellation_date() -> None:
    policies = [
        cover(1, date(2024, 1, 1), date(2025, 1, 1)),
        cover(2, date(2024, 1, 1), date(2025, 1, 1), cancellation_date=date(2024, 6, 11)),
    ]
    result = monthly(inputs_of([admin(400.0)], policies))
    assert one(result, "denominator") == pytest.approx(1 + 10 / 30)
    assert one(result) == pytest.approx(300.0)


def test_ex04_by_year_and_by_line_at_the_level_the_expense_was_booked() -> None:
    policies = [
        cover(1, date(2024, 1, 1), date(2025, 1, 1), line="A"),
        cover(2, date(2024, 1, 1), date(2025, 1, 1), line="A"),
        cover(3, date(2024, 7, 2), date(2025, 1, 1), line="B"),  # 183 of the 366 days
    ]
    months = [date(2024, m, 28) for m in range(1, 13)]
    expenses = [
        *[admin(10.0, day, segment="LIFE", line="A") for day in months],
        *[admin(5.0, day, segment="LIFE", line="B") for day in months],
        *[admin(40.0, day) for day in months],  # booked without a line
    ]
    inputs = inputs_of(expenses, policies)
    total = measure(inputs, "EX04", "calendar_period")
    assert table(total) == {("2024",): pytest.approx((120 + 60 + 480) / 2.5)}
    by_line = measure(inputs, "EX04", "segment", "line", "calendar_period")
    assert table(by_line) == {
        ("LIFE", "A", "2024"): pytest.approx(120 / 2),
        ("LIFE", "B", "2024"): pytest.approx(60 / 0.5),
    }
    # the 480 booked without a line are in no line: never spread
    assert sum(table(by_line, "numerator").values()) == 180.0
    assert any("12 expense rows without segment not allocated" in n for n in by_line.notes)


def test_ex04_no_policies_in_force_is_not_computed() -> None:
    policies = [cover(1, date(2024, 7, 1), date(2025, 1, 1))]
    result = monthly(inputs_of([admin(100.0), admin(70.0, date(2024, 7, 31))], policies))
    assert table(result) == {("2024-06",): None, ("2024-07",): pytest.approx(70.0)}
    assert table(result, "note")[("2024-06",)] == "no policies in force in the period: not computed"


def test_ex04_a_month_without_expense_rows_is_not_computed_and_is_listed() -> None:
    policies = [cover(1, date(2024, 1, 1), date(2025, 1, 1))]
    expenses = [admin(100.0, date(2024, 4, 30)), admin(100.0, date(2024, 6, 30))]
    result = monthly(inputs_of(expenses, policies))
    assert table(result) == {
        ("2024-04",): pytest.approx(100.0),
        ("2024-05",): None,  # never set to zero: a missing booking is not a zero cost
        ("2024-06",): pytest.approx(100.0),
    }
    assert table(result, "note")[("2024-05",)] == (
        "no administration expense rows in 2024-05: not computed"
    )
    year = measure(inputs_of(expenses, policies), "EX04", "calendar_period")
    assert one(year) is None  # the year holds a month without a booking
    assert one(year, "note") == "no administration expense rows in 2024-05: not computed"


def test_ex04_at_value_date_prices() -> None:
    """An index of 100 in January and 150 in December: the January cost of 100 is 150 at the
    prices of the cut-off, the December cost stays."""
    market = [
        ("CPI_TR", "PRICE_INDEX", date(2024, m, 28), 100.0 if m < 12 else 150.0)
        for m in range(1, 13)
    ]
    policies = [cover(1, date(2024, 1, 1), date(2025, 1, 1))]
    expenses = [admin(100.0, date(2024, m, 28)) for m in range(1, 13)]
    inputs = inputs_of(expenses, policies, market_rows=market)
    nominal = monthly(inputs)
    adjusted = monthly(inputs, value=ValueBasis.INFLATION_ADJUSTED)
    assert table(nominal)[("2024-01",)] == pytest.approx(100.0)
    assert table(adjusted)[("2024-01",)] == pytest.approx(150.0)
    assert table(adjusted)[("2024-12",)] == pytest.approx(100.0)
    assert any("at prices of 2024-12-31 (CPI_TR)" in n for n in adjusted.notes)


def test_ex04_says_why_it_is_not_available() -> None:
    policies = [cover(1, date(2024, 1, 1), date(2025, 1, 1))]
    inputs = inputs_of([admin(100.0)], policies)
    assert measure(inputs, "EX04").reason == (
        "EX04 is a cost per calendar period: ask for the calendar_period breakdown"
    )
    other = inputs_of([expense(type="OTHER", period=JUNE)], policies)
    assert measure(other, "EX04", "calendar_period").reason == (
        "no administration expenses in the expense file"
    )
    without = make_inputs({"claim_valuations": [cv(12)], "expenses": [admin(1.0)]}, cut_off=CUT_OFF)
    assert measure(without, "EX04", "calendar_period").reason == "policies is not loaded"
