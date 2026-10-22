"""PR06 Average premium: hand-computed fixtures of the specification."""

from datetime import date

import pytest

from tests.measures.helpers import measure, one
from tests.measures.shared import premium_inputs, pt, year_policy
from tests.quality.builders import policy


def test_pr06_average_premium_is_earned_premium_over_earned_exposure() -> None:
    """Policies of 2 and 1 exposure units cover 2024-01-01 to 2024-07-01 (182 days) and earn 600:
    exposure 3 x 182 / 365.25, average premium 600 / that."""
    policies = [
        policy(
            policy_id="A",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 7, 1),
            exposure_units=2.0,
        ),
        policy(
            policy_id="B",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 7, 1),
            exposure_units=1.0,
        ),
    ]
    rows = [
        pt("T1", "WRITTEN", date(2024, 1, 1), 400.0, policy_id="A"),
        pt("T2", "WRITTEN", date(2024, 1, 1), 200.0, policy_id="B"),
    ]
    inputs = premium_inputs(rows, policies)
    result = measure(inputs, "PR06", "calendar_period")
    assert one(result) == pytest.approx(600.0 / (3 * 182 / 365.25))
    assert one(result, "denominator") == pytest.approx(3 * 182 / 365.25)


def test_pr06_policies_without_exposure_units_count_one_per_policy_year() -> None:
    rows = [pt("T1", "WRITTEN", date(2024, 1, 1), 366.0)]
    result = measure(premium_inputs(rows, [year_policy()]), "PR06", "calendar_period")
    assert one(result, "denominator") == pytest.approx(366 / 365.25)
    assert one(result) == pytest.approx(366.0 / (366 / 365.25))
