"""PR05 Retention ratio: hand-computed fixtures of the specification."""

import pytest

from actuarycanary.convert.bases import ReinsuranceBasis
from tests.measures.helpers import measure, one
from tests.measures.shared import BOOKED, premium_inputs, pt


def test_pr05_retention_ratio_and_a_file_without_ceded_premium() -> None:
    rows = [pt("T1", "WRITTEN", BOOKED, 1000.0), pt("T2", "CEDED_PREMIUM", BOOKED, 300.0)]
    net = ReinsuranceBasis.NET
    assert one(measure(premium_inputs(rows), "PR05", reinsurance=net)) == pytest.approx(0.7)
    missing = measure(premium_inputs(rows[:1]), "PR05", reinsurance=net)
    assert missing.reason == "no ceded premium in the premium file (CV03)"


def test_pr05_outside_zero_and_one_is_shown_and_flagged() -> None:
    rows = [pt("T1", "WRITTEN", BOOKED, 100.0), pt("T2", "CEDED_PREMIUM", BOOKED, 300.0)]
    result = measure(premium_inputs(rows), "PR05", reinsurance=ReinsuranceBasis.NET)
    assert one(result) == pytest.approx(-2.0) and "outside 0 to 1" in one(result, "note")
