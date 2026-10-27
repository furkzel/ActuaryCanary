"""Generalised Pareto distribution (MT18, and the Pareto II of MT17): maximum likelihood,
standard errors, profile-likelihood interval, tail quantile, return level, expected shortfall.

The likelihood is profiled over k = xi / sigma: for a given k the maximum over xi has the closed
form xi(k) = mean(ln(1 + k y)), sigma = xi / k, and the profile log-likelihood is
l(k) = -n (ln(xi / k) + xi + 1). The profile is searched on a grid and refined by golden-section
search, for many samples at once (the bootstrap of MT18 and MT17 refits thousands of samples).
Pareto II (Lomax) with shape alpha and scale theta is the same family with xi = 1/alpha,
sigma = theta/alpha, restricted to xi > 0 (k = 1/theta).
"""

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats

from actuarycanary.methods.severity.numeric import numerical_hessian, root, standard_errors

MIN_XI = -0.5  # below it the maximum likelihood estimator is not regular (MT18)
CHI2_95 = float(stats.chi2.ppf(0.95, 1))
S_GRID_POSITIVE = np.logspace(-6, 4, 26)  # k x mean(y), searched upwards from zero
S_GRID_NEGATIVE = -np.array([0.002, 0.01, 0.03, 0.08, 0.2, 0.4, 0.6, 0.8, 0.92, 0.98, 0.999])
GOLDEN = (math.sqrt(5.0) - 1.0) / 2.0
GOLDEN_STEPS = 44
SERIES_BELOW = 1e-6  # |xi| under which the log-likelihood uses the exponential limit


@dataclass(frozen=True)
class GpdFit:
    xi: float
    sigma: float
    loglik: float
    n: int
    boundary: bool  # the search ended at the edge of its range (no interior maximum)


def _profile(y: np.ndarray, mean: np.ndarray, s: np.ndarray) -> np.ndarray:
    """Profile log-likelihood of rows `y` (B, n) at s = k x mean, one s per row."""
    k = s / mean
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        z = k[:, None] * y
        np.log1p(z, out=z)
        xi = z.mean(axis=1)
        out = -y.shape[1] * (np.log(xi / k) + xi + 1.0)
    return np.where(np.isfinite(out), out, -np.inf)


def _score(y: np.ndarray, k: float) -> float:
    """Derivative of the profile log-likelihood in k, divided by -n: zero at the maximum,
    negative below it and positive above it."""
    z = 1.0 + k * y
    xi = float(np.log(z).mean())
    return float((y / z).mean()) * (1.0 / xi + 1.0) - 1.0 / k


def _polish(y: np.ndarray, mean: float, low: float, high: float, s: float) -> float:
    """The root of the score between the grid neighbours of the maximum, when the score changes
    sign there; otherwise the golden-section result `s`. The golden search alone resolves s to
    about 1e-6 because the profile is flat at its top."""
    k_low, k_high = low / mean, high / mean
    try:
        if _score(y, k_low) < 0.0 < _score(y, k_high):
            return root(lambda k: _score(y, k), k_low, k_high, xtol=1e-15) * mean
    except (ValueError, ZeroDivisionError, FloatingPointError):
        pass
    return s


def fit_matrix(
    y: np.ndarray, *, positive_only: bool = False, polish: bool = False
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Maximum-likelihood xi and sigma of each row of `y` (B, n) of positive excesses.

    Returns xi, sigma, the log-likelihood and a boolean `boundary` per row. With
    `positive_only` the search keeps xi > 0 (Pareto II); a row whose likelihood still rises
    towards xi = 0 ends at the lowest grid point and is flagged as a boundary. `polish` finds
    the root of the score for each row (single fits; the bootstrap does not need it).
    """
    y = np.asarray(y, dtype=np.float64)
    rows = y.shape[0]
    mean = y.mean(axis=1)
    top = y.max(axis=1)
    if positive_only:
        grid = np.broadcast_to(S_GRID_POSITIVE, (rows, len(S_GRID_POSITIVE)))
    else:
        lower = (mean / top)[:, None] * S_GRID_NEGATIVE[None, :]  # k > -1 / max(y)
        grid = np.concatenate(
            [lower[:, ::-1], np.broadcast_to(S_GRID_POSITIVE, (rows, len(S_GRID_POSITIVE)))],
            axis=1,
        )
    values = np.stack([_profile(y, mean, grid[:, j]) for j in range(grid.shape[1])], axis=1)
    best = values.argmax(axis=1)
    last = grid.shape[1] - 1
    boundary = (best == 0) | (best == last)
    low = grid[np.arange(rows), np.maximum(best - 1, 0)].copy()
    high = grid[np.arange(rows), np.minimum(best + 1, last)].copy()
    # golden-section search for the maximum in [low, high]
    a, b = low, high
    c = b - GOLDEN * (b - a)
    d = a + GOLDEN * (b - a)
    fc, fd = _profile(y, mean, c), _profile(y, mean, d)
    for _ in range(GOLDEN_STEPS):
        left = fc > fd  # the maximum lies in [a, d]
        b = np.where(left, d, b)
        a = np.where(left, a, c)
        c_new = b - GOLDEN * (b - a)
        d_new = a + GOLDEN * (b - a)
        c, d = np.where(left, c_new, d), np.where(left, c, d_new)
        # one point of each row is new (c when the maximum lies left, d otherwise), the other
        # is kept: one evaluation of the profile per step, not two
        new = np.where(left, c, d)
        f_new = _profile(y, mean, new)
        fc, fd = np.where(left, f_new, fd), np.where(left, fc, f_new)
    s = (a + b) / 2.0
    if polish:
        for r in range(rows):
            if not boundary[r] and abs(s[r]) > 1e-4:
                s[r] = _polish(y[r], float(mean[r]), float(low[r]), float(high[r]), float(s[r]))
    k = s / mean
    with np.errstate(invalid="ignore", divide="ignore"):
        xi = np.log1p(k[:, None] * y).mean(axis=1)
        sigma = xi / k
    loglik = _profile(y, mean, s)
    return xi, sigma, loglik, boundary


def fit(excess: np.ndarray) -> GpdFit:
    """Maximum-likelihood fit of one sample of positive excesses."""
    y = np.asarray(excess, dtype=np.float64)
    if len(y) < 2 or not np.all(y > 0):
        raise ValueError("generalised Pareto fit needs at least two positive excesses")
    xi, sigma, loglik, boundary = fit_matrix(y[None, :], polish=True)
    return GpdFit(float(xi[0]), float(sigma[0]), float(loglik[0]), len(y), bool(boundary[0]))


def logpdf(y: np.ndarray, xi: float, sigma: float) -> np.ndarray:
    """Log density of excesses y > 0 (-inf outside the support)."""
    y = np.asarray(y, dtype=np.float64)
    z = y / sigma
    if abs(xi) < SERIES_BELOW:
        # exponential limit with the first correction in xi
        return -math.log(sigma) - z - xi * (z - z * z / 2.0)
    arg = 1.0 + xi * z
    with np.errstate(invalid="ignore", divide="ignore"):
        out = -math.log(sigma) - (1.0 / xi + 1.0) * np.log(arg)
    return np.where(arg > 0, out, -np.inf)


def loglik(y: np.ndarray, xi: float, sigma: float) -> float:
    return float(np.sum(logpdf(y, xi, sigma)))


def cdf(y: np.ndarray, xi: np.ndarray | float, sigma: np.ndarray | float) -> np.ndarray:
    """Distribution function of the excess, broadcast over rows."""
    y = np.asarray(y, dtype=np.float64)
    xi = np.asarray(xi, dtype=np.float64)
    sigma = np.asarray(sigma, dtype=np.float64)
    small = np.abs(xi) < SERIES_BELOW
    safe = np.where(small, 1.0, xi)
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        regular = -np.expm1(-np.log1p(safe * y / sigma) / safe)
        limit = -np.expm1(-y / sigma)
        out = np.where(small, limit, regular)
        out = np.where(1.0 + xi * y / sigma <= 0, 1.0, out)
    return np.clip(out, 0.0, 1.0)


def sf(y: np.ndarray, xi: np.ndarray | float, sigma: np.ndarray | float) -> np.ndarray:
    """Survival function of the excess, broadcast over rows (exact in the far tail)."""
    y = np.asarray(y, dtype=np.float64)
    xi = np.asarray(xi, dtype=np.float64)
    sigma = np.asarray(sigma, dtype=np.float64)
    small = np.abs(xi) < SERIES_BELOW
    safe = np.where(small, 1.0, xi)
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        regular = np.exp(-np.log1p(safe * y / sigma) / safe)
        limit = np.exp(-y / sigma)
        out = np.where(small, limit, regular)
        out = np.where(1.0 + xi * y / sigma <= 0, 0.0, out)
    return np.clip(out, 0.0, 1.0)


def ppf(q: np.ndarray, xi: np.ndarray | float, sigma: np.ndarray | float) -> np.ndarray:
    """Quantile function of the excess, broadcast over rows."""
    q = np.asarray(q, dtype=np.float64)
    xi = np.asarray(xi, dtype=np.float64)
    sigma = np.asarray(sigma, dtype=np.float64)
    small = np.abs(xi) < SERIES_BELOW
    safe = np.where(small, 1.0, xi)
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        regular = sigma / safe * np.expm1(-safe * np.log1p(-q))
        limit = -sigma * np.log1p(-q)
    return np.where(small, limit, regular)


def anderson_darling(y: np.ndarray, xi: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """A^2 of each row of excesses `y` (B, n) against its generalised Pareto (xi, sigma)."""
    y = np.sort(np.asarray(y, dtype=np.float64), axis=1)
    n = y.shape[1]
    xi, sigma = np.asarray(xi)[:, None], np.asarray(sigma)[:, None]
    tiny = 1e-300
    ln_f = np.log(np.maximum(cdf(y, xi, sigma), tiny))
    ln_s = np.log(np.maximum(sf(y, xi, sigma), tiny))
    weights = (2.0 * np.arange(1, n + 1) - 1.0)[None, :]
    return -n - (weights * (ln_f + ln_s[:, ::-1])).sum(axis=1) / n


def bootstrap_p_value(
    excess: np.ndarray, fitted: GpdFit, n_boot: int, rng: np.random.Generator
) -> tuple[float, float]:
    """Anderson-Darling statistic of the fit and its parametric-bootstrap p-value: samples
    are drawn from the fitted distribution and refitted before their statistic is taken.
    p = (1 + number of bootstrap statistics at or above the observed) / (B + 1)."""
    observed = float(
        anderson_darling(
            np.asarray(excess)[None, :], np.array([fitted.xi]), np.array([fitted.sigma])
        )[0]
    )
    n = len(excess)
    u = rng.random((n_boot, n))
    sample = ppf(u, fitted.xi, fitted.sigma)
    sample = np.maximum(sample, np.finfo(float).tiny)
    xi, sigma, _, _ = fit_matrix(sample)
    ok = np.isfinite(xi) & np.isfinite(sigma) & (sigma > 0)
    boot = anderson_darling(sample[ok], xi[ok], sigma[ok])
    exceed = int(np.sum(boot >= observed))
    return observed, (1 + exceed) / (len(boot) + 1)


def information(y: np.ndarray, xi: float, sigma: float) -> np.ndarray:
    """Observed information matrix of (xi, sigma)."""

    def negative(theta: np.ndarray) -> float:
        return -loglik(y, float(theta[0]), float(theta[1]))

    return numerical_hessian(negative, np.array([xi, sigma]))


def standard_errors_of(y: np.ndarray, fitted: GpdFit) -> tuple[float, float]:
    se = standard_errors(information(np.asarray(y), fitted.xi, fitted.sigma))
    return float(se[0]), float(se[1])


def _profile_at_xi(y: np.ndarray, xi: float) -> float:
    """Log-likelihood maximised over sigma for a given xi (NaN when no sigma exists).

    The score in sigma is zero where h(sigma) = (xi + 1) sum(y / (sigma + xi y)) - n = 0, which
    falls from +infinity (xi < 0) or n / xi (xi > 0) at the lowest admissible sigma to -n."""
    n = len(y)
    mean = float(y.mean())
    if abs(xi) < 1e-9:
        return -n * (math.log(mean) + 1.0)

    def score(sigma: float) -> float:
        return (xi + 1.0) * float(np.sum(y / (sigma + xi * y))) - n

    low = 1e-12 * mean if xi > 0 else -xi * float(y.max()) * (1.0 + 1e-12)
    high = max(2.0 * low, (xi + 1.0) * mean * 1.01 + low)
    for _ in range(60):
        if score(high) < 0.0:
            break
        high *= 2.0
    else:
        return math.nan
    if score(low) <= 0.0:
        return math.nan
    return loglik(y, xi, root(score, low, high, xtol=1e-14 * high))


def profile_interval(y: np.ndarray, fitted: GpdFit, level: float = 0.95) -> tuple[float, float]:
    """Profile-likelihood interval for xi: where twice the log-likelihood drop stays below the
    chi-square quantile. A side that the search does not close is NaN."""
    y = np.asarray(y, dtype=np.float64)
    cut = fitted.loglik - float(stats.chi2.ppf(level, 1)) / 2.0

    def gap(xi: float) -> float:
        return _profile_at_xi(y, xi) - cut

    def side(direction: float) -> float:
        step = max(0.05, 0.5 * abs(fitted.xi))
        inner = fitted.xi
        for _ in range(12):
            outer = inner + direction * step
            if outer <= -0.999:
                return math.nan
            g = gap(outer)
            if math.isnan(g):
                return math.nan
            if g < 0:
                return root(gap, min(inner, outer), max(inner, outer))
            inner, step = outer, step * 2.0
        return math.nan

    return side(-1.0), side(+1.0)


def tail_quantile(p: float, u: float, xi: float, sigma: float, n: int, n_exceed: int) -> float:
    """x_p of the sizes (not of the excesses): u + sigma/xi ((n/N_u (1-p))^-xi - 1); NaN when p
    lies below the exceedance level 1 - N_u/n (the quantile would be under u)."""
    ratio = n / n_exceed * (1.0 - p)
    if ratio > 1.0 + 1e-12:
        return math.nan
    if abs(xi) < SERIES_BELOW:
        return u + sigma * math.log(1.0 / ratio)
    return u + sigma / xi * (ratio ** (-xi) - 1.0)


def return_level(years: float, u: float, xi: float, sigma: float, n_exceed: int, h: float) -> float:
    """z_T: the size exceeded on average once in T years, with N_u exceedances in h years."""
    rate = n_exceed / h * years
    if rate < 1.0:
        return math.nan
    if abs(xi) < SERIES_BELOW:
        return u + sigma * math.log(rate)
    return u + sigma / xi * (rate**xi - 1.0)


def expected_shortfall(x_p: float, u: float, xi: float, sigma: float) -> float:
    """ES_p above the quantile x_p (xi below 1; NaN otherwise)."""
    if math.isnan(x_p) or xi >= 1.0:
        return math.nan
    if abs(xi) < SERIES_BELOW:
        return x_p + sigma
    return x_p / (1.0 - xi) + (sigma - xi * u) / (1.0 - xi)
