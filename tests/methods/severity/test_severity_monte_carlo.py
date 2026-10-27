"""Calibration of MT17 and MT18 on samples from the models themselves (spec ground truth).

Spec IDs proved: MT17 and MT18 (calibration). Behind ACTUARYCANARY_MONTE_CARLO=1; the counts of
the samples are the spec's where the cost allows (Wald and profile coverage) and smaller where a
parametric bootstrap sits inside every sample (family selection, the automatic threshold); they
are named in each test and in decision 0302.
"""

import os

import numpy as np
import pytest

from actuarycanary.methods.severity import extreme_values, fit_severity, gpd
from actuarycanary.methods.severity import families as fam
from tests.methods.severity.helpers import sizes_frame, spliced_quantile, spliced_sizes

MONTE_CARLO = pytest.mark.skipif(
    os.environ.get("ACTUARYCANARY_MONTE_CARLO") != "1",
    reason="Monte Carlo calibration test; set ACTUARYCANARY_MONTE_CARLO=1",
)
pytestmark = [pytest.mark.slow, MONTE_CARLO]

# Parameter sets fixed for the calibration: those of tests/benchmarks/tier_b/MT17-severity-fits
PARAMETERS = {
    fam.LOGNORMAL: (10.0, 1.2),  # mu, sigma
    fam.GAMMA: (2.5, 4000.0),  # shape, scale
    fam.WEIBULL: (1.5, 8000.0),  # shape, scale
    fam.PARETO: (3.0, 50000.0),  # alpha, theta
}
SAMPLE_SIZE = 2000
COVERAGE_SAMPLES = 1000  # the spec's count
SELECTION_SAMPLES = 200  # per family, with 100 bootstrap samples inside each
SEED = 20261025


def _draw(family: str, rng: np.random.Generator) -> np.ndarray:
    a, b = PARAMETERS[family]
    return fam.sample(family, np.array([a]), np.array([b]), SAMPLE_SIZE, rng)[0]


@pytest.mark.parametrize("family", list(PARAMETERS))
def test_mt17_wald_interval_covers_the_true_parameters(family: str) -> None:
    rng = np.random.default_rng([SEED, list(PARAMETERS).index(family)])
    truth = PARAMETERS[family]
    hits = np.zeros(2)
    for _ in range(COVERAGE_SAMPLES):
        est = fam.estimate(family, _draw(family, rng))
        for k, (value, se) in enumerate(((est.a, est.a_se), (est.b, est.b_se))):
            hits[k] += abs(value - truth[k]) <= 1.959964 * se
    coverage = hits / COVERAGE_SAMPLES
    print(f"\nMT17 {family}: 95% Wald coverage {coverage.round(3).tolist()}")
    assert np.all((coverage >= 0.90) & (coverage <= 0.99)), coverage


@pytest.mark.parametrize("family", list(PARAMETERS))
def test_mt17_the_true_family_is_selected_in_most_samples(family: str) -> None:
    rng = np.random.default_rng([SEED, 10 + list(PARAMETERS).index(family)])
    chosen = 0
    for _ in range(SELECTION_SAMPLES):
        result = fit_severity(sizes_frame(_draw(family, rng)), gof_bootstrap=100)
        chosen += result.selected["family"][0] == family
    rate = chosen / SELECTION_SAMPLES
    print(f"\nMT17 {family}: true family selected in {rate:.3f} of {SELECTION_SAMPLES} samples")
    assert rate >= 0.80


@pytest.mark.parametrize("xi", [0.3, 0.5])
def test_mt18_profile_interval_covers_the_true_xi_at_the_true_threshold(xi: float) -> None:
    rng = np.random.default_rng([SEED, 20, int(10 * xi)])
    covered = 0
    for _ in range(COVERAGE_SAMPLES):
        sizes, u0 = spliced_sizes(rng, 5000, tail_share=0.1, xi=xi)
        excess = sizes[sizes > u0] - u0
        fit = gpd.fit(excess)
        low, high = gpd.profile_interval(excess, fit)
        covered += low <= xi <= high
    coverage = covered / COVERAGE_SAMPLES
    print(f"\nMT18 xi {xi}: 95% profile interval coverage {coverage:.3f}")
    assert 0.90 <= coverage <= 0.99


@pytest.mark.parametrize("xi", [0.3, 0.5])
def test_mt18_the_automatic_threshold_gives_a_99_5th_percentile_close_to_the_truth(
    xi: float,
) -> None:
    rng = np.random.default_rng([SEED, 30, int(10 * xi)])
    samples = 100
    close = 0
    for _ in range(samples):
        sizes, u0 = spliced_sizes(rng, 5000, tail_share=0.1, xi=xi)
        truth = spliced_quantile(0.995, u0, 0.1, xi, 2e4)
        result = extreme_values(sizes_frame(sizes), gof_bootstrap=100)
        found = result.tail_quantiles.filter(result.tail_quantiles["probability"] == 0.995)[
            "quantile"
        ][0]
        close += abs(found / truth - 1.0) <= 0.25
    rate = close / samples
    print(f"\nMT18 xi {xi}: 99.5th percentile within 25% in {rate:.2f} of {samples} samples")
    assert rate >= 0.80
