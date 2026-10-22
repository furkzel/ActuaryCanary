"""RI02 Reinsurance result: hand-computed fixtures of the specification."""

import pytest

from actuarycanary.convert.bases import ReinsuranceBasis
from tests.measures.helpers import measure, one
from tests.measures.shared import inputs_for, p
from tests.quality.builders import cv


def test_ri02_reinsurance_result_is_ceded_claims_plus_commission_minus_ceded_premium() -> None:
    """Ceded incurred change 250, RI commission earned 75, ceded premium earned 300: +25."""
    row = cv(12, claim_id="K0", paid_to_date=300.0, case_reserve=200.0)
    claims_rows = [{**row, "ceded_paid_to_date": 100.0, "ceded_reserve": 150.0}]
    premiums = [p("WRITTEN", 1000.0), p("CEDED_PREMIUM", 300.0), p("RI_COMMISSION", 75.0)]
    inputs = inputs_for(premiums, claims_rows=claims_rows)
    result = measure(inputs, "RI02", "calendar_period", reinsurance=ReinsuranceBasis.CEDED)
    assert one(result) == pytest.approx(25.0)
    assert one(result, "share_of_ceded_premium") == pytest.approx(25 / 300)


def test_ri02_without_commission_counts_zero_and_without_ceded_premium_is_missing() -> None:
    row = cv(12, claim_id="K0", paid_to_date=300.0, case_reserve=200.0)
    claims_rows = [{**row, "ceded_paid_to_date": 100.0, "ceded_reserve": 150.0}]
    inputs = inputs_for([p("WRITTEN", 1000.0), p("CEDED_PREMIUM", 300.0)], claims_rows=claims_rows)
    result = measure(inputs, "RI02", "calendar_period", reinsurance=ReinsuranceBasis.CEDED)
    assert one(result) == pytest.approx(-50.0)
    assert any("RI_COMMISSION" in n for n in result.notes)
    gone = measure(
        inputs_for([p("WRITTEN", 1000.0)], claims_rows=claims_rows),
        "RI02",
        reinsurance=ReinsuranceBasis.CEDED,
    )
    assert gone.reason == "no ceded premium in the premium file (CV03)"
