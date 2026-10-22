"""PR03 Unearned premium: hand-computed fixtures of the specification."""

from datetime import date

import pytest

from tests.measures.helpers import measure, one
from tests.measures.shared import _earning_inputs


def test_pr03_unearned_premium_and_written_equals_earned_plus_unearned() -> None:
    """At 2024-12-31: T1 has 3650 - 184 x 10 = 1810 left, T2 has 2730 - 92 x 10 = 1810 left."""
    inputs = _earning_inputs()
    inputs.cut_off = date(2024, 12, 31)
    assert one(measure(inputs, "PR03")) == pytest.approx(3620.0)
    for day, written in ((date(2024, 9, 30), 3650.0), (date(2024, 12, 31), 6380.0)):
        inputs.cut_off = day
        earned_to_date = one(measure(inputs, "PR02"))
        assert earned_to_date + one(measure(inputs, "PR03")) == pytest.approx(written)


def test_pr03_after_every_policy_end_is_zero() -> None:
    inputs = _earning_inputs()
    inputs.cut_off = date(2025, 12, 31)
    assert one(measure(inputs, "PR03")) == 0.0
