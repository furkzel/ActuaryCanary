"""EX02 Expense ratio: hand-computed fixtures of the specification."""

from datetime import date

import pytest

from tests.measures.helpers import measure, one, table
from tests.measures.shared import inputs_for, p
from tests.quality.builders import expense


def test_ex02_acquisition_and_administration_over_earned_premium() -> None:
    expenses = [
        expense(type="ACQUISITION", amount=50.0, period=date(2024, 6, 30)),
        expense(type="ADMINISTRATION", amount=80.0, period=date(2024, 6, 30)),
        expense(type="OTHER", amount=20.0, period=date(2024, 6, 30)),
    ]
    inputs = inputs_for([p("WRITTEN", 1000.0)], expenses)
    assert one(measure(inputs, "EX02", "calendar_period")) == pytest.approx(0.13)
    by_type = measure(inputs, "EX02", "expense_type")
    assert table(by_type) == {
        ("ACQUISITION",): pytest.approx(0.05),
        ("ADMINISTRATION",): pytest.approx(0.08),
    }


def test_ex02_expenses_without_a_line_are_not_allocated_to_lines() -> None:
    expenses = [
        expense(type="ACQUISITION", amount=50.0, line="L", segment="S"),
        expense(type="ACQUISITION", amount=30.0),
    ]
    inputs = inputs_for([p("WRITTEN", 1000.0)], expenses)
    by_line = measure(inputs, "EX02", "line")
    assert one(by_line) == pytest.approx(0.05)
    assert any("not allocated" in n for n in by_line.notes)
    assert one(measure(inputs, "EX02")) == pytest.approx(0.08)


def test_ex02_periods_outside_the_expense_file_are_missing_not_zero() -> None:
    premiums = [p("WRITTEN", 1000.0), p("WRITTEN", 500.0, date(2023, 1, 1), n=2)]
    expenses = [expense(type="ACQUISITION", amount=50.0, period=date(2024, 6, 30))]
    inputs = inputs_for(premiums, expenses)
    assert [k[0] for k in table(measure(inputs, "EX02", "calendar_period"))] == ["2024"]
