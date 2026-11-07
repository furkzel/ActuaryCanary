"""Risk figures of a reserve distribution (RS03, RS05): value at risk, tail value at risk, and how
lines are added.

Value at risk is a quantile. For a sample the quantile is the linear interpolation between the
two nearest order statistics (numpy's default), and the tail value at risk is the mean of the
sample values at or above the quantile of the tail level; both levels, the sample size and the
number of values in the tail are returned so that the output can state its estimator. For a
lognormal reserve the figures have a closed form (`methods.mack.lognormal_range`).
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from actuarycanary.methods.mack import LognormalRange, lognormal_range
from actuarycanary.methods.seeding import generator

ESTIMATOR = (
    "empirical: VaR is the quantile (linear interpolation between order statistics), TVaR the "
    "mean of the simulated values at or above the quantile of its level"
)
LOGNORMAL_ESTIMATOR = "closed form of the lognormal with the same mean and standard deviation"
CORRELATION_STREAM = "line correlation"


@dataclass(frozen=True)
class SampleRisk:
    """Mean, spread, percentiles, VaR and TVaR of a sample of reserves (RS05)."""

    count: int
    mean: float
    standard_deviation: float
    percentiles: dict[float, float]
    var_level: float
    value_at_risk: float
    tvar_level: float
    tail_value_at_risk: float
    tail_count: int  # sample values at or above the quantile of the tail level
    negative_share: float

    @property
    def coefficient_of_variation(self) -> float:
        return self.standard_deviation / self.mean if self.mean else float("nan")


def sample_risk(
    values: np.ndarray, percentiles: Sequence[float], var_level: float, tvar_level: float
) -> SampleRisk:
    """The risk figures of simulated reserves; the standard deviation uses n - 1."""
    x = np.asarray(values, dtype=float)
    threshold = float(np.quantile(x, tvar_level))
    tail = x[x >= threshold]
    return SampleRisk(
        count=int(x.size),
        mean=float(x.mean()),
        standard_deviation=float(x.std(ddof=1)) if x.size > 1 else float("nan"),
        percentiles={p: float(np.quantile(x, p)) for p in percentiles},
        var_level=var_level,
        value_at_risk=float(np.quantile(x, var_level)),
        tvar_level=tvar_level,
        tail_value_at_risk=float(tail.mean()),
        tail_count=int(tail.size),
        negative_share=float((x < 0).mean()),
    )


def lognormal_risk(
    mean: float,
    standard_error: float,
    percentiles: Sequence[float],
    var_level: float,
    tvar_level: float,
) -> LognormalRange | None:
    """The lognormal with this mean and standard error; None when the mean is not positive or
    the standard error is zero (RS03)."""
    return lognormal_range(mean, standard_error, percentiles, var_level, tvar_level)


def combined_standard_error(standard_errors: Sequence[float], correlation: float) -> float:
    """The standard error of a sum of lines with one correlation between every pair of lines:
    sqrt(sum se^2 + 2 rho sum over pairs of se_a se_b) (RS03)."""
    se = np.asarray(standard_errors, dtype=float)
    pairs = (se.sum() ** 2 - (se**2).sum()) / 2
    return float(np.sqrt((se**2).sum() + 2 * correlation * pairs))


def add_lines(lines: Sequence[np.ndarray], correlation: float, seed: int, *keys: str) -> np.ndarray:
    """The sum of the simulated reserves of several lines, simulation by simulation.

    Correlation 0 adds simulation b of every line (the lines were simulated from independent
    streams). Otherwise each line's values are reordered by the ranks of normal scores that
    share a common factor, so that the lines have the Gaussian-copula rank correlation `rho`;
    correlation 1 pairs the values by size. The marginal distribution of each line is kept.
    """
    if not 0 <= correlation <= 1:
        raise ValueError(f"line correlation {correlation} must be between 0 and 1")
    columns = [np.asarray(line, dtype=float) for line in lines]
    if len({c.size for c in columns}) != 1:
        raise ValueError("the lines need the same number of simulations")
    if correlation == 0 or len(columns) == 1:
        return np.sum(columns, axis=0)
    n = columns[0].size
    rng = generator(seed, CORRELATION_STREAM, *keys)
    common = rng.standard_normal(n)
    total = np.zeros(n)
    for column in columns:
        scores = np.sqrt(correlation) * common + np.sqrt(1 - correlation) * rng.standard_normal(n)
        ranks = np.argsort(np.argsort(scores, kind="stable"), kind="stable")
        total += np.sort(column)[ranks]
    return total
