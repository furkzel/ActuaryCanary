"""RC03 Recovery delay: hand-computed fixtures of the specification."""

from datetime import date

import pytest

from tests.measures.helpers import measure, one, table
from tests.measures.recovery_fixtures import (
    BOOKINGS,
    OTHER,
    SAL,
    SUB,
    VALUATIONS,
    book,
    booking,
    valuation,
)


def test_rc03_days_from_the_month_end_of_the_first_payment_to_the_booking() -> None:
    """A claim first paid in January and recovered on 15 April: the days between the January
    month end and 15 April."""
    rows = [valuation("K", date(2024, 1, 20), 500.0), valuation("K", date(2024, 4, 30), 500.0)]
    inputs = book([booking(1, "K", date(2024, 4, 15), 40.0, SUB)], rows, triangles=False)
    result = measure(inputs, "RC03", "recovery_type")
    assert table(result) == {(SUB,): 75.0}  # 29 days of February, 31 of March, 15 of April
    assert one(result, "n") == 1 and one(result, "p50") == 75.0
    assert one(result, "p90") is None  # fewer than five recoveries


def test_rc03_mean_median_and_percentile_by_type() -> None:
    # claim A was first paid in January 2022 (month end 2022-01-31), claim B in November 2023
    result = measure(book(BOOKINGS), "RC03", "recovery_type")
    a_june, a_march, a_february = 135, 394, 731  # days from 2022-01-31
    b_may = 157  # days from 2023-11-30 to 2024-05-05
    assert table(result) == {
        (SAL,): float(a_march),
        (SUB,): pytest.approx((a_june + a_february + b_may) / 3),
    }
    assert table(result, "p50") == {(SAL,): float(a_march), (SUB,): float(b_may)}
    assert table(result, "n") == {(SAL,): 1, (SUB,): 3}
    overall = measure(book(BOOKINGS), "RC03")
    assert one(overall) == pytest.approx((a_june + a_march + a_february + b_may) / 4)
    assert any("recovery transactions" in n for n in overall.notes)


def test_rc03_derived_flows_give_month_end_differences() -> None:
    result = measure(book(None), "RC03", "recovery_type")
    # the flows are booked on the valuation dates: 2022-06-30, 2023-03-31, 2024-02-29, 2024-05-31
    assert table(result) == {(SAL,): 424.0, (SUB,): pytest.approx((150 + 759 + 183) / 3)}
    assert "derived flows: delays are whole months between month ends" in result.notes
    assert any(n.startswith("source: derived from subrogation_to_date") for n in result.notes)
    assert result.concepts == ("claim_valuations",)


def test_rc03_by_segment_line_and_origin() -> None:
    result = measure(book(BOOKINGS), "RC03", "segment", "line", "origin_period")
    assert table(result, "n") == {("NON_LIFE", "L", "2022"): 3, ("NON_LIFE", "L", "2023"): 1}


def test_rc03_recoveries_before_the_first_payment_and_reversals_are_kept_out() -> None:
    bookings = [
        *BOOKINGS,
        booking(5, "A", date(2022, 1, 5), 9.0, SUB),  # before the first payment
        booking(6, "Z", date(2024, 3, 1), 9.0, SUB),  # a claim that was never paid
        booking(7, "A", date(2024, 6, 1), -10.0, SUB),  # a reversal
        booking(8, "A", date(2024, 7, 1), 5.0, OTHER),
        booking(9, "A", date(2024, 8, 1), 5.0, "UNMAPPED"),
    ]
    by_type = measure(book(bookings), "RC03", "recovery_type")
    assert table(by_type, "n") == {(OTHER,): 1, (SAL,): 1, (SUB,): 3}
    notes = " | ".join(by_type.notes)
    assert "2 recoveries booked before the first payment of their claim" in notes
    assert "1 reversals" in notes
    assert "1 bookings with a type outside the classes are in no view by type" in notes
    assert one(measure(book(bookings), "RC03"), "n") == 6  # the unmapped type counts in the total


def test_rc03_the_ninetieth_percentile_needs_five_recoveries() -> None:
    extra = [booking(10 + k, "A", date(2022, 2, 1 + k), 1.0, SUB) for k in range(2)]
    result = measure(book([*BOOKINGS, *extra]), "RC03", "recovery_type")
    assert table(result, "n")[(SUB,)] == 5
    assert table(result, "p90")[(SUB,)] == pytest.approx(501.4)  # of 1, 2, 135, 157, 731 days
    assert table(result, "p90")[(SAL,)] is None


def test_rc03_without_recovery_data_says_so() -> None:
    bare = [
        {k: v for k, v in row.items() if not k.endswith("_to_date") or k == "paid_to_date"}
        for row in VALUATIONS
    ]
    assert measure(book(None, bare), "RC03").reason == "no recovery data"
