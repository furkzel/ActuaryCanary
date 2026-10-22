"""RI01 Cession ratio: hand-computed fixtures of the specification."""

import pytest

from actuarycanary.convert.bases import ReinsuranceBasis
from tests.measures.helpers import measure, table
from tests.measures.shared import inputs_for, p
from tests.quality.builders import cv


def _ceded_claims():
    row = cv(12, claim_id="K0", paid_to_date=300.0, case_reserve=200.0)
    return [{**row, "ceded_paid_to_date": 120.0, "ceded_reserve": 80.0}]


def test_ri01_premium_and_claims_cession_ratios() -> None:
    """Gross written 1000, ceded 300; gross incurred 500, ceded 200: 0.3 and 0.4."""
    inputs = inputs_for(
        [p("WRITTEN", 1000.0), p("CEDED_PREMIUM", 300.0)], claims_rows=_ceded_claims()
    )
    result = measure(inputs, "RI01", reinsurance=ReinsuranceBasis.CEDED)
    assert table(result) == {("premium",): pytest.approx(0.3), ("claims",): pytest.approx(0.4)}


def test_ri01_without_the_ceded_columns_only_the_premium_ratio_is_shown() -> None:
    inputs = inputs_for([p("WRITTEN", 1000.0), p("CEDED_PREMIUM", 300.0)])
    result = measure(inputs, "RI01", reinsurance=ReinsuranceBasis.CEDED)
    assert table(result) == {("premium",): pytest.approx(0.3)}
    assert any("ceded_paid_to_date" in n for n in result.notes)


def test_ri01_with_neither_side_is_not_available() -> None:
    result = measure(inputs_for([p("WRITTEN", 1000.0)]), "RI01", reinsurance=ReinsuranceBasis.CEDED)
    assert not result.available
