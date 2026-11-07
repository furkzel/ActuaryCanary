"""MT16 frequency–severity projection: hand fixture, properties and failure modes."""

import numpy as np
import pytest

from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.frequency_severity import FrequencySeverity, frequency_severity
from tests.methods.tier_b import series, table, triangle, value

HAND = "MT16-frequency-severity-4x4"


def _fixture() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    counts, _, _ = triangle(HAND, "reported_counts.csv")
    incurred, _, _ = triangle(HAND, "incurred.csv")
    exposure = np.array([float(r["earned_exposure"]) for r in table(HAND, "exposure.csv")])
    return counts, incurred, exposure


def _run(counts, measure, **options) -> FrequencySeverity:
    result = frequency_severity(counts, measure, **options)
    assert isinstance(result, FrequencySeverity)
    return result


def test_hand_fixture() -> None:
    counts, incurred, exposure = _fixture()
    result = _run(counts, incurred, exposure=exposure)
    np.testing.assert_allclose(result.count_chain.factors, series(HAND, "count_factor"), rtol=1e-12)
    np.testing.assert_allclose(
        result.measure_chain.factors, series(HAND, "incurred_factor"), rtol=1e-12
    )
    np.testing.assert_allclose(result.ultimate_counts, series(HAND, "ultimate_count_N"), rtol=1e-12)
    np.testing.assert_allclose(
        result.reported_share, series(HAND, "incurred_reported_share_p"), rtol=1e-12
    )
    np.testing.assert_allclose(result.severity, series(HAND, "severity_chain_ladder"), rtol=1e-12)
    assert result.frequency is not None and result.frequency_trend is not None
    np.testing.assert_allclose(result.frequency, series(HAND, "frequency"), rtol=1e-12)
    assert result.frequency_trend.slope == pytest.approx(
        value(HAND, "frequency_trend", "slope"), rel=1e-9
    )
    assert result.frequency_trend.intercept == pytest.approx(
        value(HAND, "frequency_trend", "intercept"), rel=1e-9
    )
    assert result.severity_trend.origins == (0, 1, 2)
    assert result.severity_trend.slope == pytest.approx(
        value(HAND, "severity_trend", "slope"), rel=1e-9
    )
    assert result.severity_trend.intercept == pytest.approx(
        value(HAND, "severity_trend", "intercept"), rel=1e-9
    )
    np.testing.assert_allclose(
        result.projected_severity, series(HAND, "projected_severity"), rtol=1e-9
    )
    expected = series(HAND, "frequency_severity_ultimate")
    np.testing.assert_allclose(result.ultimate, expected[:4], rtol=1e-9)
    assert result.ultimate.sum() == pytest.approx(expected[4], rel=1e-9)
    assert result.diagnostics == ()


def test_constant_real_severity_gives_counts_times_the_mean_mature_severity() -> None:
    counts, _, exposure = _fixture()
    severity = 5.0
    measure = counts * severity  # every origin has the same severity, no trend
    result = _run(counts, measure, exposure=exposure)
    assert result.severity_trend.slope == pytest.approx(0, abs=1e-12)
    np.testing.assert_allclose(result.ultimate, result.ultimate_counts * severity, rtol=1e-12)


def test_too_few_mature_origins_hold_severity_constant() -> None:
    counts, incurred, exposure = _fixture()
    result = _run(counts, incurred, exposure=exposure, maturity_for_trend=0.97)
    assert result.severity_trend.origins == (0, 1) and result.severity_trend.slope == 0
    mean = result.severity[[0, 1]].mean()
    np.testing.assert_allclose(result.projected_severity, mean, rtol=1e-12)
    assert [d.code for d in result.diagnostics] == ["SEVERITY_HELD_CONSTANT"]


def test_without_exposure_and_with_catastrophes() -> None:
    counts, incurred, _ = _fixture()
    cat = np.full_like(incurred, np.nan)
    cat[np.isfinite(incurred)] = 0.0
    cat[1, :3] = [100.0, 150.0, 150.0]
    base = _run(counts, incurred)
    with_cat = _run(counts, incurred, catastrophes=cat)
    assert base.frequency is None and [d.code for d in base.diagnostics] == ["NO_EXPOSURE"]
    np.testing.assert_allclose(with_cat.ultimate - base.ultimate, [0.0, 150.0, 0.0, 0.0], atol=1e-9)


def test_failure_modes() -> None:
    counts, incurred, _ = _fixture()
    found = frequency_severity(counts[:2, :2], incurred[:2, :2])
    assert isinstance(found, Skipped) and found.reason.startswith("count chain ladder")
    assert isinstance(frequency_severity(counts, incurred, maturity_for_trend=1.01), Skipped)
