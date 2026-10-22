"""RC01 Subrogation ratio: hand-computed fixtures of the specification."""

import pytest

from actuarycanary.convert.bases import ReinsuranceBasis
from actuarycanary.structures.periods import Period
from tests.measures.helpers import make_inputs, measure, one, table
from tests.quality.builders import cv


def test_rc01_subrogation_ratio_cumulative_and_as_flows() -> None:
    rows = [
        cv(1, paid_to_date=400.0, case_reserve=0.0, subrogation_to_date=20.0),
        cv(2, paid_to_date=1000.0, case_reserve=0.0, subrogation_to_date=80.0),
    ]
    inputs = make_inputs({"claim_valuations": rows})
    assert one(measure(inputs, "RC01", "origin_period")) == pytest.approx(0.08)
    flows = measure(inputs, "RC01", "calendar_period", period=Period.MONTH)
    assert table(flows) == {("2024-01",): pytest.approx(0.05), ("2024-02",): pytest.approx(0.1)}


def test_rc_without_the_column_say_so_and_zero_paid_is_not_computed() -> None:
    rows = [cv(1, paid_to_date=0.0, case_reserve=5.0, subrogation_to_date=0.0)]
    inputs = make_inputs({"claim_valuations": rows})
    assert one(measure(inputs, "RC01"), "note") == "paid is zero: not computed"
    missing = measure(inputs, "RC02")
    assert missing.reason == "no salvage column in claim_valuations"


def test_rc_not_on_ceded_or_net_basis() -> None:
    rows = [
        cv(1, paid_to_date=10.0, subrogation_to_date=1.0, ceded_paid_to_date=0.0, ceded_reserve=0.0)
    ]
    result = measure(
        make_inputs({"claim_valuations": rows}), "RC01", reinsurance=ReinsuranceBasis.NET
    )
    assert not result.available
    assert "NET" in result.reason
