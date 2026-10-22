"""MT05 expected loss ratio method: the trivial fixture and the failure modes."""

import numpy as np

from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.expected_loss_ratio import ExpectedLossRatio, expected_loss_ratio


def test_fixture_premium_1000_ratio_07_incurred_750() -> None:
    result = expected_loss_ratio([1000.0], 0.7, [750.0])
    assert isinstance(result, ExpectedLossRatio)
    assert result.ultimate.tolist() == [700.0]
    assert result.ibnr.tolist() == [-50.0]
    assert result.negative_ibnr.tolist() == [True]


def test_per_origin_ratios_and_premium_failures() -> None:
    result = expected_loss_ratio(
        [1000.0, 0.0, 500.0, 800.0], [0.7, 0.7, np.nan, 0.5], [100.0, 0.0, 10.0, 300.0]
    )
    assert isinstance(result, ExpectedLossRatio)
    assert result.not_run == {
        1: "earned premium 0 is not positive",
        2: "no expected loss ratio available",
    }
    np.testing.assert_array_equal(result.ultimate, [700.0, np.nan, np.nan, 400.0])
    assert result.negative_ibnr.tolist() == [False, False, False, False]


def test_no_ratio_and_wrong_axis_are_not_run() -> None:
    assert expected_loss_ratio([1000.0], np.nan, [0.0]) == Skipped(
        "MT05", "no expected loss ratio available"
    )
    skipped = expected_loss_ratio([1000.0], 0.7, [0.0], origin_axis="report")
    assert isinstance(skipped, Skipped)
    assert "accident or underwriting origins" in skipped.reason
