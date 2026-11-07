"""Calibration of MT19 on samples from the model itself (spec ground truth).

Spec IDs proved: MT19 (calibration). Behind ACTUARYCANARY_MONTE_CARLO=1. Weibull proportional
hazards with known coefficients and independent censoring: the 95 per cent Wald interval of each
coefficient must cover the truth in 90 to 99 per cent of the samples. The sample counts are the
spec's: 1,000 samples of 2,000 subjects, fixed seed. Run with `-s` to see the coverage.
"""

import os
import time

import numpy as np
import pytest

from actuarycanary.methods.survival.cox import cox_fit
from tests.methods.survival.helpers import fitted, weibull_sample

MONTE_CARLO = pytest.mark.skipif(
    os.environ.get("ACTUARYCANARY_MONTE_CARLO") != "1",
    reason="Monte Carlo calibration test; set ACTUARYCANARY_MONTE_CARLO=1",
)
pytestmark = [pytest.mark.slow, MONTE_CARLO]

SAMPLES = 1000
SUBJECTS = 2000
SEED = 20261027
TRUTH = np.array([0.5, -0.3, 0.8])
NAMES = ("a", "b", "c")
BAND = (0.90, 0.99)


def _coverage(ties: str, rounded: bool) -> tuple[np.ndarray, float]:
    rng = np.random.default_rng([SEED, int(rounded)])
    hits = np.zeros(len(TRUTH))
    started = time.perf_counter()
    for _ in range(SAMPLES):
        t, event, x = weibull_sample(rng, SUBJECTS, TRUTH, shape=1.5, censor_rate=0.4)
        if rounded:
            t = np.maximum(np.round(t, 2), 0.01)  # rounded to two decimals: event times are tied
        fit = fitted(cox_fit(t, event, x, NAMES, ties=ties))
        hits += (fit.hazard_ratio_lower <= np.exp(TRUTH)) & (
            np.exp(TRUTH) <= fit.hazard_ratio_upper
        )
    return hits / SAMPLES, time.perf_counter() - started


def _show(label: str, coverage: np.ndarray, seconds: float) -> None:
    shown = dict(zip(NAMES, coverage.round(3).tolist(), strict=True))
    print(f"MT19 coverage {label}: {shown} ({seconds:.0f} s)")


@pytest.mark.parametrize("ties", ["efron", "breslow"])
def test_the_95_per_cent_interval_covers_each_coefficient_without_ties(ties: str) -> None:
    coverage, seconds = _coverage(ties, rounded=False)
    _show(f"{ties}, continuous times", coverage, seconds)
    assert np.all((BAND[0] <= coverage) & (coverage <= BAND[1])), coverage


def test_the_95_per_cent_interval_covers_each_coefficient_with_many_ties_under_efron() -> None:
    coverage, seconds = _coverage("efron", rounded=True)
    _show("efron, tied times", coverage, seconds)
    assert np.all((BAND[0] <= coverage) & (coverage <= BAND[1])), coverage
