"""RT02 Combined ratio: hand-computed fixtures of the specification."""

from datetime import date

import pytest

from actuarycanary.convert.bases import ReinsuranceBasis
from tests.measures.helpers import measure, one
from tests.measures.shared import _loss_inputs, p
from tests.quality.builders import expense


def test_rt02_combined_ratio_is_ultimate_loss_plus_expense_plus_commission() -> None:
    """0.72 + 0.13 + 0.15 = 1.00."""
    expenses = [
        expense(type="ACQUISITION", amount=50.0, period=date(2024, 6, 30)),
        expense(type="ADMINISTRATION", amount=80.0, period=date(2024, 6, 30)),
    ]
    inputs = _loss_inputs([p("COMMISSION", 150.0, n=2)], expenses)
    result = measure(inputs, "RT02", "origin_period")
    assert one(result) == pytest.approx(1.0)
    assert one(result, "ultimate_loss_ratio") == pytest.approx(0.72)


def test_rt02_without_commission_is_not_computed_because_it_would_understate() -> None:
    expenses = [expense(type="ACQUISITION", amount=50.0, period=date(2024, 6, 30))]
    result = measure(_loss_inputs(expenses=expenses), "RT02", "origin_period")
    assert "would understate" in result.reason


def test_rt02_net_basis_is_not_in_version_1() -> None:
    result = measure(_loss_inputs(), "RT02", reinsurance=ReinsuranceBasis.NET)
    assert not result.available
