"""EX05 Claims-handling cost per claim: hand-computed fixtures of the specification."""

from datetime import date

import pytest

from actuarycanary.structures.periods import Period
from tests.measures.helpers import make_inputs, measure
from tests.quality.builders import cv, expense

FEB, MAR = date(2024, 2, 29), date(2024, 3, 31)


def handling(amount: float, period: date, **more) -> dict:
    return expense(type="CLAIMS_HANDLING_UNALLOCATED", amount=amount, period=period, **more)


def claim_rows(
    claim: int, months: range, allocated: dict[int, float] | None = None, **more
) -> list:
    rows = []
    for month in months:
        values = dict(more)
        if allocated is not None:
            values["expense_allocated_to_date"] = allocated.get(month, 0.0)
        rows.append(cv(month, claim_id=str(claim), **values))
    return rows


def book(expenses: list[dict], allocated: bool = True) -> dict:
    """Ten claims open since January and five reported in March; claim 1 carries allocated
    handling costs of 100 booked in March."""
    valuations = []
    for claim in range(1, 11):
        cost = {3: 100.0} if claim == 1 else {}
        valuations += claim_rows(claim, range(1, 4), cost if allocated else None)
    for claim in range(11, 16):
        valuations += claim_rows(claim, range(3, 4), {} if allocated else None)
    return {"claim_valuations": valuations, "expenses": expenses}


def table(result, column: str = "value") -> dict:
    """Values by calendar period (the frame also names the components of the numerator)."""
    assert result.frame is not None, result.reason
    return {(r["calendar_period"],): r[column] for r in result.frame.iter_rows(named=True)}


def monthly(rows: dict, *breakdowns: str):
    inputs = make_inputs(rows, cut_off=MAR)
    return measure(inputs, "EX05", *breakdowns, "calendar_period", period=Period.MONTH)


def test_ex05_ten_open_plus_five_reported_claims_and_costs_of_300() -> None:
    """Ten open plus five reported claims and handling costs of 300 (100 allocated, 200
    unallocated) give 20 per claim."""
    expenses = [handling(50.0, date(2024, 1, 31)), handling(60.0, FEB), handling(200.0, MAR)]
    result = monthly(book(expenses))
    assert table(result)[("2024-03",)] == pytest.approx(20.0)
    assert table(result, "numerator")[("2024-03",)] == 300.0
    assert table(result, "denominator")[("2024-03",)] == 15.0
    assert table(result)[("2024-02",)] == pytest.approx(60.0 / 10)  # ten open, none reported
    assert set(result.frame["components"]) == {"allocated and unallocated"}  # type: ignore[index]


def test_ex05_the_first_period_has_no_open_count_at_its_start() -> None:
    expenses = [handling(50.0, date(2024, 1, 31)), handling(60.0, FEB), handling(200.0, MAR)]
    result = monthly(book(expenses))
    assert table(result)[("2024-01",)] is None
    assert table(result, "note")[("2024-01",)] == (
        "first period of the file: the open count at its start is unknown"
    )


def test_ex05_without_an_allocated_column_is_unallocated_only_and_says_so() -> None:
    expenses = [handling(60.0, FEB), handling(150.0, MAR)]
    result = monthly(book(expenses, allocated=False))
    assert table(result)[("2024-03",)] == pytest.approx(150.0 / 15)
    assert set(result.frame["components"]) == {"unallocated only"}  # type: ignore[index]
    assert any("unallocated only" in n for n in result.notes)


def test_ex05_without_unallocated_expenses_is_allocated_only() -> None:
    result = monthly(book([expense(type="OTHER", period=MAR)]))
    assert table(result)[("2024-03",)] == pytest.approx(100.0 / 15)
    assert set(result.frame["components"]) == {"allocated only"}  # type: ignore[index]


def test_ex05_a_month_without_expense_rows_is_not_computed_and_is_listed() -> None:
    expenses = [handling(50.0, date(2024, 1, 31)), handling(200.0, MAR)]
    result = monthly(book(expenses))
    assert table(result)[("2024-02",)] is None
    assert table(result, "note")[("2024-02",)] == (
        "no unallocated claims-handling expense rows in 2024-02: not computed"
    )
    assert table(result)[("2024-03",)] == pytest.approx(20.0)


def test_ex05_no_claims_handled_is_not_computed() -> None:
    rows = {
        "claim_valuations": [
            cv(1, status="CLOSED", case_reserve=0.0),
            cv(2, status="CLOSED", case_reserve=0.0),
            cv(3, status="CLOSED", case_reserve=0.0),
        ],
        "expenses": [handling(10.0, date(2024, 1, 31)), handling(10.0, FEB), handling(10.0, MAR)],
    }
    result = monthly(rows)
    assert table(result)[("2024-03",)] is None
    assert table(result, "note")[("2024-03",)] == "no claims handled in the period: not computed"


def test_ex05_says_why_it_is_not_available() -> None:
    rows = book([expense(type="OTHER", period=MAR)], allocated=False)
    inputs = make_inputs(rows, cut_off=MAR)
    assert measure(inputs, "EX05", "calendar_period").reason == (
        "neither allocated claims expense in claim_valuations nor "
        "CLAIMS_HANDLING_UNALLOCATED expenses were loaded"
    )
    assert measure(inputs, "EX05").reason == (
        "EX05 is a cost per calendar period: ask for the calendar_period breakdown"
    )
