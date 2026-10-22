"""PR02 Earned premium: hand-computed fixtures of the specification."""

from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from actuarycanary.structures.periods import Period
from tests.measures.helpers import measure, one, table, values
from tests.measures.shared import BOOKED, _earning_inputs, premium_inputs, pt, year_policy
from tests.structures.test_premium import MONTHLY


def test_pr02_earned_premium_by_month_of_the_endorsed_and_cancelled_policy() -> None:
    result = measure(_earning_inputs(), "PR02", "calendar_period", period=Period.MONTH)
    earned = table(result)
    labels = [f"2024-{m:02d}" for m in range(7, 13)] + [f"2025-{m:02d}" for m in range(1, 7)]
    assert [earned[(label,)] for label in labels] == pytest.approx(MONTHLY)
    assert sum(values(result)) == pytest.approx(4570.0)  # the written premium of the expired policy


@settings(max_examples=10)
@given(st.integers(0, 200))
def test_pr02_earned_over_all_periods_equals_written_for_an_expired_policy(extra: int) -> None:
    rows = [pt("T1", "WRITTEN", date(2024, 1, 1), 1000.0 + extra)]
    inputs = premium_inputs(rows, [year_policy()], cut_off=date(2025, 12, 31))
    assert one(measure(inputs, "PR02", period=Period.MONTH)) == pytest.approx(1000.0 + extra)


def test_pr_measures_say_so_when_policies_are_missing() -> None:
    rows = [pt("T1", "WRITTEN", BOOKED, 100.0)]
    for measure_id in ("PR02", "PR03", "PR06"):
        assert measure(premium_inputs(rows), measure_id).reason == "policies is not loaded"
