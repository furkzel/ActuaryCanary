"""RC04 Recovery development ratio: hand-computed fixtures of the specification."""

from datetime import date

import pytest

from actuarycanary.convert.bases import ValueBasis
from tests.measures.helpers import measure, one, table
from tests.measures.recovery_fixtures import (
    BOOKINGS,
    OTHER,
    SAL,
    SUB,
    VALUATIONS,
    book,
    booking,
)

VIEW = ("recovery_type", "origin_period", "development_period")
# cumulative recoveries over the paid triangle 100, 200, 300 / 50, 150 / 80
TOTAL = {
    ("TOTAL", "2022", "12"): pytest.approx(10 / 100),
    ("TOTAL", "2022", "24"): pytest.approx(30 / 200),
    ("TOTAL", "2022", "36"): pytest.approx(60 / 300),
    ("TOTAL", "2023", "12"): 0.0,
    ("TOTAL", "2023", "24"): pytest.approx(15 / 150),
    ("TOTAL", "2024", "12"): 0.0,
}
BY_TYPE = {
    (SUB, "2022", "12"): pytest.approx(10 / 100),
    (SUB, "2022", "24"): pytest.approx(10 / 200),
    (SUB, "2022", "36"): pytest.approx(40 / 300),
    (SAL, "2022", "12"): 0.0,
    (SAL, "2022", "24"): pytest.approx(20 / 200),
    (SAL, "2022", "36"): pytest.approx(20 / 300),
    (SUB, "2023", "24"): pytest.approx(15 / 150),
}


def _picked(result, keys) -> dict:
    values = table(result)
    return {k: values[k] for k in keys}


def test_rc04_three_by_three_triangle_from_transactions() -> None:
    result = measure(book(BOOKINGS), "RC04", *VIEW)
    assert _picked(result, TOTAL) == TOTAL
    assert _picked(result, BY_TYPE) == BY_TYPE
    assert table(result, "numerator")[("TOTAL", "2022", "36")] == 60.0
    assert table(result, "denominator")[("TOTAL", "2022", "36")] == 300.0
    assert {k[0] for k in table(result)} == {SUB, SAL, OTHER, "TOTAL"}
    assert result.concepts == ("recoveries",)


def test_rc04_transactions_and_derived_flows_give_the_same_triangle_when_they_agree() -> None:
    derived = measure(book(None), "RC04", *VIEW)
    assert _picked(derived, TOTAL) == TOTAL
    assert _picked(derived, BY_TYPE) == BY_TYPE
    assert {k[0] for k in table(derived)} == {SUB, SAL, "TOTAL"}  # no other recoveries
    assert "the total is subrogation plus salvage only (no recoveries feed)" in derived.notes
    assert derived.concepts == ("claim_valuations",)


def test_rc04_other_recoveries_count_in_the_total_and_under_their_type() -> None:
    bookings = [
        *BOOKINGS,
        booking(5, "B", date(2024, 6, 1), 6.0, OTHER),
        booking(6, "B", date(2024, 7, 1), 9.0, "UNMAPPED"),
    ]
    result = measure(book(bookings), "RC04", *VIEW)
    assert table(result)[(OTHER, "2023", "24")] == pytest.approx(6 / 150)
    assert table(result)[("TOTAL", "2023", "24")] == pytest.approx(21 / 150)  # without the unmapped
    whole = measure(book(bookings), "RC04", "origin_period", "development_period")
    assert table(whole)[("2023", "24")] == pytest.approx(30 / 150)  # the unmapped booking counts


def test_rc04_without_development_periods_takes_the_latest_diagonal() -> None:
    result = measure(book(BOOKINGS), "RC04", "origin_period")
    assert table(result) == {
        ("2022",): pytest.approx(60 / 300),
        ("2023",): pytest.approx(15 / 150),
        ("2024",): 0.0,
    }
    assert one(measure(book(BOOKINGS), "RC04")) == pytest.approx(75 / 530)


def test_rc04_zero_paid_is_not_computed() -> None:
    from tests.measures.recovery_fixtures import NAN, triangle_set

    inputs = book(BOOKINGS)
    inputs.triangles = triangle_set([[100.0, 200.0, 300.0], [0.0, 150.0, NAN], [80.0, NAN, NAN]])
    result = measure(inputs, "RC04", "origin_period", "development_period")
    assert table(result)[("2023", "12")] is None
    assert table(result, "note")[("2023", "12")] == "paid is zero: not computed"


def test_rc04_a_recovery_on_a_claim_without_a_valuation_is_in_no_origin_view() -> None:
    bookings = [*BOOKINGS, booking(5, "Z", date(2024, 3, 1), 99.0, SUB)]
    result = measure(book(bookings), "RC04", *VIEW)
    assert _picked(result, TOTAL) == TOTAL
    assert any("1 recoveries on claims without a valuation" in n for n in result.notes)


def test_rc04_says_why_it_is_not_available() -> None:
    bare = [
        {k: v for k, v in row.items() if not k.endswith("_to_date") or k == "paid_to_date"}
        for row in VALUATIONS
    ]
    assert measure(book(None, bare), "RC04").reason == "no recovery data"
    assert measure(book(BOOKINGS, triangles=False), "RC04").reason == (
        "no triangles were built (MT01)"
    )
    adjusted = measure(book(BOOKINGS), "RC04", value=ValueBasis.INFLATION_ADJUSTED)
    assert adjusted.reason == "the triangles are built on NOMINAL, not on INFLATION_ADJUSTED"
