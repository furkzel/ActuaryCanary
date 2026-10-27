"""AE02 back-test error of a projection: errors per origin, weighted bias and MAE, edge cases.

The computation lives in `methods.back_testing` until the measure engine wires AE02 (decision
0284)."""

import numpy as np
import pytest

from actuarycanary.methods.back_testing import ae02_errors, weighted_errors


def test_spec_example() -> None:
    errors = ae02_errors([110.0, 95.0], [100.0, 100.0])
    np.testing.assert_allclose(errors, [0.10, -0.05], rtol=1e-12)
    bias, mae, rmse = weighted_errors(errors, [100.0, 100.0])
    assert mae == pytest.approx(0.075, rel=1e-12)
    assert bias == pytest.approx(0.025, rel=1e-12)
    assert rmse == pytest.approx(np.sqrt((0.01 + 0.0025) / 2), rel=1e-12)


def test_weights_are_the_reference_ultimates() -> None:
    errors = ae02_errors([110.0, 285.0], [100.0, 300.0])
    bias, mae, _ = weighted_errors(errors, [100.0, 300.0])
    assert bias == pytest.approx((100 * 0.1 + 300 * -0.05) / 400, rel=1e-12)
    assert mae == pytest.approx((100 * 0.1 + 300 * 0.05) / 400, rel=1e-12)


def test_reference_zero_or_missing_estimate_is_not_computed() -> None:
    errors = ae02_errors([110.0, 50.0, np.nan], [100.0, 0.0, 80.0])
    assert errors[0] == pytest.approx(0.1) and np.isnan(errors[1]) and np.isnan(errors[2])
    bias, mae, rmse = weighted_errors(errors, [100.0, 0.0, 80.0])
    assert (bias, mae, rmse) == pytest.approx((0.1, 0.1, 0.1), rel=1e-12)
