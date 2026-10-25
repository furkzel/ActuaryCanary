"""Numerical helpers of the severity methods: Hessian of a log-likelihood and standard errors."""

import math
from collections.abc import Callable
from typing import cast

import numpy as np
from scipy import optimize, stats

RELATIVE_STEP = 1e-4


def numerical_hessian(f: Callable[[np.ndarray], float], theta: np.ndarray) -> np.ndarray:
    """Hessian of `f` at `theta` by central differences, step 1e-4 of each parameter."""
    theta = np.asarray(theta, dtype=np.float64)
    n = len(theta)
    step = RELATIVE_STEP * np.maximum(np.abs(theta), 1e-8)
    hessian = np.empty((n, n))
    centre = f(theta)
    for i in range(n):
        up, down = theta.copy(), theta.copy()
        up[i] += step[i]
        down[i] -= step[i]
        hessian[i, i] = (f(up) - 2.0 * centre + f(down)) / step[i] ** 2
        for j in range(i + 1, n):
            pp, pm, mp, mm = theta.copy(), theta.copy(), theta.copy(), theta.copy()
            pp[i] += step[i]
            pp[j] += step[j]
            pm[i] += step[i]
            pm[j] -= step[j]
            mp[i] -= step[i]
            mp[j] += step[j]
            mm[i] -= step[i]
            mm[j] -= step[j]
            hessian[i, j] = hessian[j, i] = (f(pp) - f(pm) - f(mp) + f(mm)) / (
                4.0 * step[i] * step[j]
            )
    return hessian


def standard_errors(information: np.ndarray) -> np.ndarray:
    """Square roots of the diagonal of the inverse of the observed information (the Hessian of
    the negative log-likelihood); NaN when the matrix is not positive definite."""
    n = len(information)
    if not np.all(np.isfinite(information)):
        return np.full(n, np.nan)
    try:
        np.linalg.cholesky(information)
        covariance = np.linalg.inv(information)
    except np.linalg.LinAlgError:
        return np.full(n, np.nan)
    return np.sqrt(np.diag(covariance))


def root(f: Callable[[float], float], low: float, high: float, xtol: float = 1e-12) -> float:
    """The root of `f` between `low` and `high` (the signs of f at the ends must differ)."""
    return cast(float, optimize.brentq(f, low, high, xtol=xtol))


def log_linear_trend(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Least-squares slope of `y` on `x`, its standard error and the two-sided p-value of the
    slope (Student t, n - 2 degrees of freedom); NaN where fewer than three points or no spread."""
    n = len(x)
    centred = x - x.mean()
    spread = float(np.sum(centred**2))
    if n < 3 or spread <= 0.0:
        return math.nan, math.nan, math.nan
    slope = float(np.sum(centred * (y - y.mean())) / spread)
    residual = y - y.mean() - slope * centred
    error = math.sqrt(float(np.sum(residual**2)) / (n - 2) / spread)
    if error == 0.0:
        return slope, 0.0, 0.0
    p_value = 2.0 * float(stats.t.sf(abs(slope) / error, n - 2))
    return slope, error, p_value
