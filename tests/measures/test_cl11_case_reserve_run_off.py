"""CL11 Case reserve run-off: hand-computed fixtures of the specification."""

from datetime import date

import pytest

from tests.measures.helpers import make_inputs, measure, one
from tests.quality.builders import cv


def test_cl11_run_off_of_the_cohort_with_a_reserve_at_the_earlier_valuation() -> None:
    """Reserves 100, 50 and 0 at v0. Since then A paid 40 and holds 50, B paid 20 and holds 50,
    C paid 10 and holds 20. The cohort is A and B: (90 + 70) / 150; C is outside it."""
    rows = [
        cv(12, claim_id="A", paid_to_date=100.0, case_reserve=100.0),
        cv(12, claim_id="B", paid_to_date=100.0, case_reserve=50.0),
        cv(12, claim_id="C", paid_to_date=100.0, case_reserve=0.0),
    ]
    rows = [{**r, "valuation_date": date(2023, 12, 31)} for r in rows] + [
        {
            **cv(12, claim_id="A", paid_to_date=140.0, case_reserve=50.0),
            "valuation_date": date(2024, 12, 31),
        },
        {
            **cv(12, claim_id="B", paid_to_date=120.0, case_reserve=50.0),
            "valuation_date": date(2024, 12, 31),
        },
        {
            **cv(12, claim_id="C", paid_to_date=110.0, case_reserve=20.0),
            "valuation_date": date(2024, 12, 31),
        },
    ]
    result = measure(make_inputs({"claim_valuations": rows}), "CL11", "origin_period")
    assert one(result) == pytest.approx(160 / 150)
    assert one(result, "run_off_result") == pytest.approx(-10.0)  # reserve 150 minus 160 needed
    assert one(result, "claims") == 1 + 1


def test_cl11_claim_without_a_row_after_the_earlier_valuation_is_carried_forward_and_listed() -> (
    None
):
    rows = [
        {
            **cv(12, claim_id="A", paid_to_date=0.0, case_reserve=100.0),
            "valuation_date": date(2023, 12, 31),
        },
        {
            **cv(12, claim_id="B", paid_to_date=0.0, case_reserve=10.0),
            "valuation_date": date(2023, 12, 31),
        },
        {
            **cv(12, claim_id="B", paid_to_date=10.0, case_reserve=0.0),
            "valuation_date": date(2024, 12, 31),
        },
    ]
    result = measure(make_inputs({"claim_valuations": rows}), "CL11")
    assert one(result, "numerator") == 100.0 + 10.0  # A's last reserve carried forward; B paid 10
    assert result.tables["carried_forward"]["claim_id"].to_list() == ["A"]


def test_cl11_cohort_reserve_zero_is_not_computed() -> None:
    rows = [
        {
            **cv(12, claim_id="A", paid_to_date=0.0, case_reserve=0.0),
            "valuation_date": date(2023, 12, 31),
        },
        {
            **cv(12, claim_id="A", paid_to_date=5.0, case_reserve=0.0),
            "valuation_date": date(2024, 12, 31),
        },
    ]
    assert one(measure(make_inputs({"claim_valuations": rows}), "CL11")) is None
