"""CL01 Paid claims: hand-computed fixtures of the specification."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from actuarycanary.measures.model import CurrencyView
from actuarycanary.structures.periods import Period
from tests.measures.helpers import make_inputs, measure, one, table, values
from tests.measures.shared import APR30, FEB29, MONTH_ENDS, four_months
from tests.quality.builders import cv


def _original():

    return CurrencyView.ORIGINAL


def test_cl01_paid_at_each_month_end_and_as_flows() -> None:
    inputs = four_months()
    stock = measure(inputs, "CL01", "valuation_date")
    assert [table(stock)[(d,)] for d in MONTH_ENDS] == [400.0, 400.0, 450.0, 530.0]
    flows = measure(inputs, "CL01", "calendar_period", period=Period.MONTH)
    assert table(flows) == {
        ("2024-01",): 400.0,
        ("2024-02",): 0.0,
        ("2024-03",): 50.0,
        ("2024-04",): 80.0,
    }
    # the decrease of claim C stays a negative flow, so flows and cumulative views agree
    assert sum(values(flows)) == table(stock)[(APR30,)]


@settings(max_examples=10)
@given(st.lists(st.lists(st.integers(0, 50), min_size=1, max_size=6), min_size=1, max_size=4))
def test_cl01_flows_to_a_date_sum_to_cumulative_paid(increments: list[list[int]]) -> None:
    rows = []
    for k, steps in enumerate(increments):
        paid = 0.0
        for month, step in enumerate(steps, start=1):
            paid += step
            rows.append(cv(month, claim_id=f"K{k}", paid_to_date=paid, case_reserve=0.0))
    inputs = make_inputs({"claim_valuations": rows})
    flows = measure(inputs, "CL01", "calendar_period", period=Period.MONTH)
    total = measure(inputs, "CL01")
    assert sum(values(flows)) == pytest.approx(one(total))


def test_cl01_empty_paid_row_is_left_out_of_paid_and_flow_runs_between_the_rows_that_have_it() -> (
    None
):
    rows = [
        cv(1, paid_to_date=10.0),
        cv(2, paid_to_date=None),
        cv(3, paid_to_date=40.0),
    ]
    inputs = make_inputs({"claim_valuations": rows})
    flows = measure(inputs, "CL01", "calendar_period", period=Period.MONTH)
    assert table(flows) == {("2024-01",): 10.0, ("2024-03",): 30.0}
    assert table(measure(inputs, "CL01", "valuation_date"))[(FEB29,)] == 10.0


def test_cl01_original_view_never_adds_currencies() -> None:
    rows = [
        cv(1, claim_id="A", paid_to_date=10.0),
        cv(1, claim_id="B", paid_to_date=5.0, currency="USD"),
    ]
    result = measure(make_inputs({"claim_valuations": rows}), "CL01", currency=_original())
    assert table(result) == {("TRY",): 10.0, ("USD",): 5.0}


def test_cl01_amounts_without_a_rate_are_left_out_and_reported() -> None:
    rows = [
        cv(1, claim_id="A", paid_to_date=10.0),
        cv(1, claim_id="B", paid_to_date=5.0, currency="USD"),
    ]
    result = measure(make_inputs({"claim_valuations": rows}), "CL01")
    assert one(result) == 10.0
    assert any("USD" in note for note in result.notes)
