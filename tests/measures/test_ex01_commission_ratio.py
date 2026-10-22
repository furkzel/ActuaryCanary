"""EX01 Commission ratio: hand-computed fixtures of the specification."""

import pytest

from actuarycanary.structures.periods import Period
from tests.measures.helpers import measure, values
from tests.measures.shared import inputs_for, p


def test_ex01_commission_earned_like_premium_over_earned_premium() -> None:
    inputs = inputs_for([p("WRITTEN", 1200.0), p("COMMISSION", 180.0)])
    result = measure(inputs, "EX01", "calendar_period", period=Period.MONTH)
    assert values(result) == pytest.approx([0.15] * 12)


def test_ex01_without_commission_rows_is_not_computed_never_zero() -> None:
    result = measure(inputs_for([p("WRITTEN", 1200.0)]), "EX01")
    assert result.reason == "no commission in the premium file"
