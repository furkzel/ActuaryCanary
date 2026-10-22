"""EX03 Claims-handling expense ratio: hand-computed fixtures of the specification."""

from datetime import date

import pytest

from tests.measures.helpers import measure, one
from tests.measures.shared import inputs_for
from tests.quality.builders import cv, expense


def _handling_rows(allocated: float | None):
    row = cv(12, claim_id="K0", paid_to_date=1000.0, case_reserve=0.0)
    return [{**row, "expense_allocated_to_date": allocated}] if allocated is not None else [row]


def test_ex03_allocated_and_unallocated_over_paid() -> None:
    expenses = [expense(type="CLAIMS_HANDLING_UNALLOCATED", amount=20.0, period=date(2024, 12, 31))]
    inputs = inputs_for(claims_rows=_handling_rows(30.0), expenses=expenses)
    result = measure(inputs, "EX03", "calendar_period")
    assert one(result) == pytest.approx(0.05)
    assert one(result, "allocated_ratio") == pytest.approx(0.03)
    assert one(result, "unallocated_ratio") == pytest.approx(0.02)
    assert one(result, "components") == "allocated and unallocated"


def test_ex03_without_the_expense_file_the_allocated_ratio_is_shown_and_labelled() -> None:
    result = measure(inputs_for(claims_rows=_handling_rows(30.0)), "EX03", "calendar_period")
    assert one(result) == pytest.approx(0.03)
    assert one(result, "components") == "allocated only"


def test_ex03_with_neither_component_is_not_available() -> None:
    result = measure(inputs_for(claims_rows=_handling_rows(None)), "EX03")
    assert not result.available and "CLAIMS_HANDLING_UNALLOCATED" in result.reason
