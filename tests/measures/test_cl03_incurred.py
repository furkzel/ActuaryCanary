"""CL03 Incurred claims (reported): hand-computed fixtures of the specification."""

import pytest

from actuarycanary.convert.bases import ValueBasis
from actuarycanary.structures.periods import Period
from tests.convert.fixtures import FEB, JAN
from tests.measures.helpers import make_inputs, measure, one, table, values
from tests.measures.shared import MONTH_ENDS, four_months
from tests.quality.builders import cv


def test_cl03_incurred_is_paid_plus_reserve_and_its_movement_by_month() -> None:
    inputs = four_months()
    stock = measure(inputs, "CL03", "valuation_date")
    assert [table(stock)[(d,)] for d in MONTH_ENDS] == [1200.0, 1100.0, 1060.0, 1000.0]
    movement = measure(inputs, "CL03", "calendar_period", period=Period.MONTH)
    assert values(movement) == [1200.0, -100.0, -40.0, -60.0]


def test_cl03_inflation_adjusted_is_restated_paid_flows_plus_restated_reserve() -> None:
    """Index 100 in January and 200 in February; value date February. Paid flows: 100 in
    January restated x2, 50 in February x1: 250. Reserve of February 100 x1. Incurred 350."""
    rows = [
        cv(1, paid_to_date=100.0, case_reserve=200.0),
        cv(2, paid_to_date=150.0, case_reserve=100.0),
    ]
    market = [("CPI_TR", "PRICE_INDEX", JAN, 100.0), ("CPI_TR", "PRICE_INDEX", FEB, 200.0)]
    inputs = make_inputs({"claim_valuations": rows}, market_rows=market)
    adjusted = measure(inputs, "CL03", value=ValueBasis.INFLATION_ADJUSTED)
    assert one(adjusted) == pytest.approx(350.0)
    assert one(measure(inputs, "CL03")) == pytest.approx(250.0)  # nominal 150 + 100
