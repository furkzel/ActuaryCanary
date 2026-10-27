"""MT15 separation method: exact fixture, properties and failure modes."""

import numpy as np
import pytest

from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.separation import NO_TAIL_LABEL, FutureIndex, Separation, separation
from tests.methods.helpers import fitted
from tests.methods.tier_b import series, table, triangle, value

HAND = "MT15-separation-4x4"


def _fixture() -> tuple[np.ndarray, np.ndarray]:
    incremental, _, _ = triangle(HAND, "incremental_paid.csv")
    counts = np.array([float(r["ultimate_claim_count"]) for r in table(HAND, "claim_counts.csv")])
    return incremental, counts


def _run(incremental, counts, **options) -> Separation:
    result = separation(incremental, counts, **options)
    assert isinstance(result, Separation)
    return result


def test_fixture_gives_back_n_r_lambda_and_the_projection_with_the_known_index() -> None:
    incremental, counts = _fixture()
    result = _run(incremental, counts, future_index=FutureIndex.ASSUMPTION, rate=0.05)
    np.testing.assert_allclose(result.diagonal_sums, series(HAND, "diagonal_sum_d"), rtol=1e-12)
    np.testing.assert_allclose(result.column_sums, series(HAND, "column_sum_v"), rtol=1e-12)
    lam = [value(HAND, "calendar_index_lambda", f"k{k}") for k in range(4)]
    r = [value(HAND, "development_pattern_r", f"dev{j}") for j in range(4)]
    np.testing.assert_allclose(result.index[:4], lam, rtol=1e-12)
    np.testing.assert_allclose(result.pattern, r, rtol=1e-12)
    assert result.pattern.sum() == pytest.approx(1.0, rel=1e-12)
    np.testing.assert_allclose(
        result.reserve, series(HAND, "reserve_assumed_5pct"), rtol=1e-12, atol=1e-12
    )
    np.testing.assert_allclose(result.ultimate, series(HAND, "ultimate_assumed_5pct"), rtol=1e-12)
    assert result.reserve.sum() == pytest.approx(
        value(HAND, "total_reserve_assumed_5pct", "all"), rel=1e-12
    )
    assert result.projected[3, 3] == pytest.approx(
        value(HAND, "projected_increment_assumed_5pct", "2024_dev3"), rel=1e-12
    )
    np.testing.assert_allclose(result.residuals[np.isfinite(result.residuals)], 0, atol=1e-12)
    assert result.tail_label == NO_TAIL_LABEL


def test_fixture_with_the_trend_of_the_index() -> None:
    incremental, counts = _fixture()
    result = _run(incremental, counts)
    assert result.growth == pytest.approx(value(HAND, "future_index_trend", "growth_g"), rel=1e-9)
    assert result.trend_periods == 4  # fewer diagonals than the default 5
    np.testing.assert_allclose(
        result.reserve, series(HAND, "reserve_ols_trend"), rtol=1e-9, atol=1e-9
    )
    assert result.reserve.sum() == pytest.approx(
        value(HAND, "total_reserve_ols_trend", "all"), rel=1e-9
    )
    np.testing.assert_allclose(
        result.implied_rates[:3], [0.1, 125 / 110 - 1, 140 / 125 - 1], rtol=1e-12
    )


def test_scaling_scales_lambda_and_keeps_r() -> None:
    incremental, counts = _fixture()
    base, scaled = _run(incremental, counts), _run(incremental * 7.5, counts)
    np.testing.assert_allclose(scaled.index, base.index * 7.5, rtol=1e-9)
    np.testing.assert_allclose(scaled.pattern, base.pattern, rtol=1e-9)


def test_constant_index_gives_the_chain_ladder_on_per_claim_amounts() -> None:
    n = np.array([10.0, 12.0, 15.0, 20.0])
    r = np.array([0.6, 0.25, 0.1, 0.05])
    incremental = np.array(
        [[n[i] * r[j] * 50.0 if i + j <= 3 else np.nan for j in range(4)] for i in range(4)]
    )
    result = _run(incremental, n, future_index=FutureIndex.ASSUMPTION, rate=0.0)
    per_claim = np.cumsum(np.nan_to_num(incremental / n[:, None]), axis=1)
    per_claim[np.isnan(incremental)] = np.nan
    chain = fitted(per_claim)
    np.testing.assert_allclose(result.ultimate, chain.ultimate * n, rtol=1e-9)


def test_inflation_comparison_and_residual_means() -> None:
    incremental, counts = _fixture()
    result = _run(incremental, counts)
    rows = result.inflation_comparison({1: 0.08, 3: 0.11})
    assert [(row["diagonal"], row["reference"]) for row in rows] == [(1.0, 0.08), (3.0, 0.11)]
    assert rows[0]["implied"] == pytest.approx(0.1, rel=1e-12)
    means = result.residuals_by()
    assert set(means) == {"origin", "development", "diagonal"}
    np.testing.assert_allclose(means["diagonal"], 0, atol=1e-12)


def test_failure_modes() -> None:
    incremental, counts = _fixture()
    assert separation(incremental[:, :3], counts) == Skipped(
        "MT15", "separation needs equal origin and development periods"
    )
    zero = counts.copy()
    zero[2] = 0
    assert separation(incremental, zero) == Skipped(
        "MT15", "separation needs claim counts per origin"
    )
    assert isinstance(separation(incremental, counts[:3]), Skipped)
    with pytest.raises(ValueError, match="rate"):
        separation(incremental, counts, future_index=FutureIndex.ASSUMPTION)
    # a negative increment on the latest diagonal: r(1) = 10 / 9 leaves nothing for diagonal 0
    found = separation(np.array([[100.0, 10.0], [-1.0, np.nan]]), np.ones(2))
    assert found == Skipped("MT15", "the pattern leaves nothing for diagonal 0 (1 - sum of r <= 0)")
