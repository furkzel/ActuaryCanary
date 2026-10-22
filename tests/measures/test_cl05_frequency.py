"""CL05 Claim frequency: hand-computed fixtures of the specification."""

from datetime import date

import pytest

from tests.measures.helpers import make_inputs, measure, one, table
from tests.quality.builders import claim, cv, policy


def _frequency_inputs():
    """Four claims occurred in 2024, one of them nil-closed; 30 exposure years in 2024."""
    units = 30 * 365.25 / 366  # one policy covering 366 days earns exactly 30 exposure years
    policies = [
        policy(
            policy_id="P1",
            segment="S",
            line="L",
            start_date=date(2024, 1, 1),
            end_date=date(2025, 1, 1),
            exposure_units=units,
        )
    ]
    claims = [claim(claim_id=f"K{i}", segment="S", line="L") for i in range(4)]
    rows = [cv(12, claim_id=f"K{i}", status="CLOSED_NIL" if i == 3 else "OPEN") for i in range(4)]
    return make_inputs({"claim_valuations": rows, "claims": claims, "policies": policies})


def test_cl05_frequency_excludes_nil_claims_by_default() -> None:
    inputs = _frequency_inputs()
    result = measure(inputs, "CL05", "segment", "line", "origin_period")
    assert one(result) == pytest.approx(3 / 30)
    assert one(result, "note") == "reported frequency"
    with_nil = measure(inputs, "CL05", "origin_period", params=(("exclude_nil", False),))
    assert one(with_nil) == pytest.approx(4 / 30)


def test_cl05_zero_exposure_is_not_computed_and_missing_policies_say_so() -> None:
    rows = [cv(12, claim_id="K0")]
    claims = [claim(claim_id="K0", segment="S", line="L")]
    far = [policy(start_date=date(2030, 1, 1), end_date=date(2031, 1, 1), segment="S", line="L")]
    inputs = make_inputs({"claim_valuations": rows, "claims": claims, "policies": far})
    result = measure(inputs, "CL05", "segment", "line", "origin_period")
    assert table(result) == {("S", "L", "2024"): None}
    without = measure(make_inputs({"claim_valuations": rows, "claims": claims}), "CL05")
    assert without.reason == "policies is not loaded"


def test_cl05_accident_periods_before_the_claims_data_are_missing_not_zero() -> None:
    policies = [
        policy(segment="S", line="L", start_date=date(2023, 1, 1), end_date=date(2025, 1, 1))
    ]
    claims = [claim(claim_id="K0", segment="S", line="L")]
    inputs = make_inputs(
        {"claim_valuations": [cv(12, claim_id="K0")], "claims": claims, "policies": policies}
    )
    assert [k[2] for k in table(measure(inputs, "CL05", "segment", "line", "origin_period"))] == [
        "2024"
    ]
