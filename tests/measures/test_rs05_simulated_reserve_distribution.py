"""RS05 simulated reserve distribution and its risk figures; RS03 across lines.

Spec IDs proved: RS05 (and RS03 for the lognormal side of M12). Ten given simulated reserves give
the hand-computed percentiles, VaR and TVaR; samples drawn at the quantiles of distributions with a
closed form give their VaR and TVaR; the lines add as the spec says.
"""

import numpy as np
import pytest
from scipy.stats import norm

from actuarycanary.measures.risk import (
    ESTIMATOR,
    add_lines,
    combined_standard_error,
    lognormal_risk,
    sample_risk,
)

LEVELS = ((0.5, 0.75, 0.9, 0.95, 0.99, 0.995), 0.995, 0.99)
TEN = np.arange(10, 101, 10, dtype=float)  # 10, 20, ..., 100


def test_ten_given_reserves_give_the_hand_computed_figures() -> None:
    found = sample_risk(TEN, *LEVELS)
    assert found.count == 10 and found.mean == 55.0
    assert found.standard_deviation == pytest.approx(np.sqrt(8250 / 9), rel=1e-14)
    # linear interpolation between order statistics at position p (n - 1)
    assert found.percentiles[0.5] == pytest.approx(55.0)  # position 4.5: 50 and 60
    assert found.percentiles[0.9] == pytest.approx(91.0)  # position 8.1: 90 + 0.1 * 10
    assert found.percentiles[0.95] == pytest.approx(95.5)  # position 8.55
    assert found.value_at_risk == pytest.approx(99.55)  # position 8.955
    # the quantile at 0.99 is 99.1; one value (100) lies at or above it
    assert found.tail_value_at_risk == 100.0 and found.tail_count == 1
    assert found.coefficient_of_variation == pytest.approx(found.standard_deviation / 55.0)


def test_the_tail_value_at_risk_is_the_mean_of_the_values_at_or_above_the_quantile() -> None:
    sample = np.arange(1.0, 101.0)  # 1 .. 100
    found = sample_risk(sample, (0.5,), 0.95, 0.90)
    # the 0.90 quantile is 90.1 (position 89.1): the values 91 .. 100 are at or above it
    assert found.tail_count == 10 and found.tail_value_at_risk == pytest.approx(95.5)
    assert found.value_at_risk == pytest.approx(95.05)  # position 94.05
    assert found.tail_value_at_risk >= found.value_at_risk  # TVaR at the lower level may be below
    assert "mean of the simulated values at or above the quantile" in ESTIMATOR


def test_a_negative_simulation_is_kept_and_its_share_stated() -> None:
    found = sample_risk(np.array([-2.0, 1.0, 2.0, 3.0]), (0.5,), 0.9, 0.9)
    assert found.negative_share == 0.25 and found.mean == 1.0


def test_a_constant_sample_has_no_spread() -> None:
    found = sample_risk(np.full(50, 7.0), *LEVELS)
    assert found.standard_deviation == 0.0 and found.value_at_risk == 7.0
    assert found.tail_value_at_risk == 7.0 and found.tail_count == 50


# --- closed forms --------------------------------------------------------------------------------


def stratified(inverse_cdf, n: int = 200_000) -> np.ndarray:  # noqa: ANN001
    """The quantiles at (k + 1/2) / n: an n-point sample whose empirical figures converge to the
    distribution's without sampling error."""
    return inverse_cdf((np.arange(n) + 0.5) / n)


def test_an_exponential_sample_gives_its_closed_form_var_and_tvar() -> None:
    scale, p = 100.0, 0.99
    sample = stratified(lambda u: -scale * np.log1p(-u))
    found = sample_risk(sample, (0.5,), 0.995, p)
    assert found.value_at_risk == pytest.approx(-scale * np.log(1 - 0.995), rel=1e-4)
    tvar = -scale * np.log(1 - p) + scale  # VaR_p + mean excess, memoryless
    assert found.tail_value_at_risk == pytest.approx(tvar, rel=1e-3)
    assert found.percentiles[0.5] == pytest.approx(scale * np.log(2), rel=1e-4)


def test_a_normal_sample_gives_its_closed_form_var_and_tvar() -> None:
    mean, sd, p = 1000.0, 150.0, 0.99
    sample = stratified(lambda u: mean + sd * norm.ppf(u))
    found = sample_risk(sample, (0.5,), 0.995, p)
    assert found.value_at_risk == pytest.approx(mean + sd * norm.ppf(0.995), rel=1e-4)
    assert found.tail_value_at_risk == pytest.approx(
        mean + sd * norm.pdf(norm.ppf(p)) / (1 - p), rel=1e-3
    )


def test_a_lognormal_sample_matches_the_closed_form_of_the_mack_side() -> None:
    reserve, se = 100.0, 20.0
    closed = lognormal_risk(reserve, se, *LEVELS)
    assert closed is not None
    sigma, mu = closed.sigma, closed.mu
    sample = stratified(lambda u: np.exp(mu + sigma * norm.ppf(u)))
    found = sample_risk(sample, *LEVELS)
    assert found.mean == pytest.approx(reserve, rel=1e-3)
    assert found.standard_deviation == pytest.approx(se, rel=2e-2)
    assert found.value_at_risk == pytest.approx(closed.value_at_risk, rel=1e-4)
    assert found.tail_value_at_risk == pytest.approx(closed.tail_value_at_risk, rel=2e-3)
    for p in LEVELS[0]:
        assert found.percentiles[p] == pytest.approx(closed.percentiles[p], rel=1e-4)


# --- lines added ---------------------------------------------------------------------------------


def test_the_standard_error_of_lines_added_with_one_correlation() -> None:
    assert combined_standard_error([3.0, 4.0], 0.0) == 5.0
    assert combined_standard_error([3.0, 4.0], 1.0) == pytest.approx(7.0)
    assert combined_standard_error([3.0, 4.0], 0.5) == pytest.approx(np.sqrt(9 + 16 + 12))
    assert combined_standard_error([1.0, 2.0, 2.0], 0.0) == 3.0
    assert combined_standard_error([5.0], 0.7) == 5.0
    # three lines at correlation 1: the standard errors add
    assert combined_standard_error([1.0, 2.0, 3.0], 1.0) == pytest.approx(6.0)


def test_independent_lines_add_simulation_by_simulation() -> None:
    rng = np.random.default_rng(1)
    a, b = rng.gamma(4.0, 25.0, 1000), rng.gamma(2.0, 50.0, 1000)
    np.testing.assert_array_equal(add_lines([a, b], 0.0, 1), a + b)
    np.testing.assert_array_equal(add_lines([a], 0.9, 1), a)


def test_perfectly_correlated_lines_add_the_values_of_the_same_size() -> None:
    rng = np.random.default_rng(2)
    a, b = rng.gamma(4.0, 25.0, 1000), rng.gamma(2.0, 50.0, 1000)
    total = add_lines([a, b], 1.0, 1)
    np.testing.assert_allclose(np.sort(total), np.sort(a) + np.sort(b), rtol=1e-13)


def test_a_correlation_keeps_each_line_whole_and_gives_the_rank_correlation_of_the_copula() -> None:
    rng = np.random.default_rng(3)
    a, b = rng.gamma(4.0, 25.0, 20_000), rng.gamma(2.0, 50.0, 20_000)
    total = add_lines([a, b], 0.5, 1)
    assert total.sum() == pytest.approx((a + b).sum(), rel=1e-12)  # a reordering, nothing else
    # the variance of the sum shows the correlation: var(a) + var(b) + 2 cov
    cov = (total.var() - a.var() - b.var()) / 2
    rank = (6 / np.pi) * np.arcsin(0.5 / 2)  # Spearman of the Gaussian copula at 0.5
    assert cov / (a.std() * b.std()) == pytest.approx(rank, abs=0.03)
    # the same seed, the same total; another key, another reordering
    np.testing.assert_array_equal(total, add_lines([a, b], 0.5, 1))
    assert not np.array_equal(total, add_lines([a, b], 0.5, 1, "other"))


def test_lines_need_the_same_number_of_simulations_and_a_correlation_in_range() -> None:
    with pytest.raises(ValueError, match="same number"):
        add_lines([np.ones(3), np.ones(4)], 0.0, 1)
    with pytest.raises(ValueError, match="between 0 and 1"):
        add_lines([np.ones(3), np.ones(3)], 1.5, 1)


def test_the_lognormal_of_the_lines_added_has_the_summed_mean_and_the_combined_error() -> None:
    se = combined_standard_error([20.0, 10.0], 0.0)
    total = lognormal_risk(100.0 + 50.0, se, *LEVELS)
    assert total is not None and total.standard_error == pytest.approx(np.sqrt(500.0))
    alone = lognormal_risk(150.0, 22.360679775, *LEVELS)
    assert alone is not None and total.value_at_risk == pytest.approx(alone.value_at_risk)
