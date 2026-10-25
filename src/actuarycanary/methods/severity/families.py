"""The four severity families of MT17: density, distribution function, quantile function,
limited expected value, and maximum-likelihood estimation with location fixed at zero.

Parameters are always a pair (a, b), in the order of `PARAMETER_NAMES`:
lognormal (mu, sigma), gamma (shape, scale), Weibull (shape, scale) and Pareto II
(alpha, theta; the Lomax distribution, survival (1 + x/theta)^-alpha).

Without truncation the estimators are closed-form or one-dimensional and run on many samples at
once (rows of a matrix), which the parametric bootstrap needs. With a truncation point d > 0
the likelihood is conditioned on X > d and is maximised numerically.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy import optimize, special

from actuarycanary.methods.severity import gpd
from actuarycanary.methods.severity.numeric import numerical_hessian, standard_errors

LOGNORMAL, GAMMA, WEIBULL, PARETO = "lognormal", "gamma", "weibull", "pareto"
FAMILIES = (LOGNORMAL, GAMMA, WEIBULL, PARETO)
PARAMETER_NAMES = {
    LOGNORMAL: ("mu", "sigma"),
    GAMMA: ("shape", "scale"),
    WEIBULL: ("shape", "scale"),
    PARETO: ("alpha", "theta"),
}
MAX_NEWTON = 60
STEP_TOLERANCE = 1e-11  # relative size of the last Newton step that ends the iteration
CONVERGED_WITHIN = 1e-8  # a root whose last step is smaller than this counts as found
EDGE = (1e-6, 1e9)  # estimates outside this range sit at the edge of the parameter space
HALF_LOG_2PI = 0.5 * math.log(2.0 * math.pi)
Array = np.ndarray


class FamilyError(ValueError):
    """A family name that is not one of the four."""


def _check(family: str) -> None:
    if family not in FAMILIES:
        raise FamilyError(f"unknown family {family!r}; allowed: {', '.join(FAMILIES)}")


def logpdf(family: str, x: Array, a: Array | float, b: Array | float) -> Array:
    _check(family)
    x = np.asarray(x, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        if family == LOGNORMAL:
            lx = np.log(x)
            return -lx - np.log(b) - HALF_LOG_2PI - (lx - a) ** 2 / (2.0 * np.square(b))
        if family == GAMMA:
            return (a - 1.0) * np.log(x) - x / b - special.gammaln(a) - a * np.log(b)
        if family == WEIBULL:
            return np.log(a) - np.log(b) + (a - 1.0) * (np.log(x) - np.log(b)) - (x / b) ** a
        return np.log(a) - np.log(b) - (a + 1.0) * np.log1p(x / b)


def cdf(family: str, x: Array, a: Array | float, b: Array | float) -> Array:
    _check(family)
    x = np.asarray(x, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        if family == LOGNORMAL:
            return special.ndtr((np.log(x) - a) / b)
        if family == GAMMA:
            return special.gammainc(a, x / b)
        if family == WEIBULL:
            return -np.expm1(-((x / b) ** a))
        return -np.expm1(-a * np.log1p(x / b))


def sf(family: str, x: Array, a: Array | float, b: Array | float) -> Array:
    """Survival function, exact in the far tail."""
    _check(family)
    x = np.asarray(x, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        if family == LOGNORMAL:
            return special.ndtr(-(np.log(x) - a) / b)
        if family == GAMMA:
            return special.gammaincc(a, x / b)
        if family == WEIBULL:
            return np.exp(-((x / b) ** a))
        return np.exp(-a * np.log1p(x / b))


def ppf(family: str, q: Array | float, a: Array | float, b: Array | float) -> Array:
    _check(family)
    q = np.asarray(q, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        if family == LOGNORMAL:
            return np.exp(a + b * special.ndtri(q))
        if family == GAMMA:
            return b * special.gammaincinv(a, q)
        if family == WEIBULL:
            return b * (-np.log1p(-q)) ** (1.0 / a)
        return b * np.expm1(-np.log1p(-q) / a)


def limited_expected_value(family: str, limit: float, a: float, b: float) -> float:
    """E[X ^ L] = integral of the survival function from 0 to L."""
    _check(family)
    if limit <= 0:
        return 0.0
    if family == LOGNORMAL:
        z = (math.log(limit) - a) / b
        return math.exp(a + b * b / 2.0) * float(special.ndtr(z - b)) + limit * float(
            special.ndtr(-z)
        )
    if family == GAMMA:
        t = limit / b
        return a * b * float(special.gammainc(a + 1.0, t)) + limit * float(special.gammaincc(a, t))
    if family == WEIBULL:
        t = (limit / b) ** a
        inverse = 1.0 + 1.0 / a
        return b * math.exp(special.gammaln(inverse)) * float(
            special.gammainc(inverse, t)
        ) + limit * math.exp(-t)
    if abs(a - 1.0) < 1e-12:
        return b * math.log1p(limit / b)
    return b / (a - 1.0) * (-math.expm1((1.0 - a) * math.log1p(limit / b)))


def mean_is_finite(family: str, a: float) -> bool:
    return not (family == PARETO and a <= 1.0)


# ------------------------------------------------------------------ estimation


def _safeguarded_newton(
    f: Callable[[Array], tuple[Array, Array]],
    start: Array,
    low: Array,
    high: Array,
    increasing: bool,
) -> tuple[Array, Array]:
    """Root of a monotone f for each row: Newton steps kept inside a shrinking bracket.
    Returns the roots and a boolean per row for convergence."""
    x = np.clip(start, low, high)
    low, high = low.copy(), high.copy()
    last = np.full(x.shape, np.inf)
    for _ in range(MAX_NEWTON):
        value, slope = f(x)
        above = value > 0 if increasing else value < 0  # the root lies below x
        high = np.where(above, x, high)
        low = np.where(above, low, x)
        with np.errstate(invalid="ignore", divide="ignore"):
            step = x - value / slope
        bad = ~np.isfinite(step) | (step < low) | (step > high)
        new = np.where(bad, (low + high) / 2.0, step)
        last = np.abs(new - x) / np.abs(new)
        x = new
        if (last <= STEP_TOLERANCE).all():
            break
    return x, last <= CONVERGED_WITHIN


def mle_matrix(family: str, x: Array) -> tuple[Array, Array, Array]:
    """Maximum-likelihood parameters (a, b) of each row of `x` (B, n), no truncation, and a
    boolean per row: False where the estimate sits at the edge of its range or did not converge
    (a Pareto II whose likelihood still rises towards an infinite shape, a sample of equal
    values)."""
    _check(family)
    x = np.asarray(x, dtype=np.float64)
    rows = x.shape[0]
    if family == LOGNORMAL:
        lx = np.log(x)
        sigma = lx.std(axis=1)
        return lx.mean(axis=1), sigma, sigma > 0
    if family == GAMMA:
        mean = x.mean(axis=1)
        lx_mean = np.log(x).mean(axis=1)
        s = np.log(mean) - lx_mean  # >= 0 by Jensen
        ok = s > 1e-12
        s = np.maximum(s, 1e-12)
        a = (3.0 - s + np.sqrt((s - 3.0) ** 2 + 24.0 * s)) / (12.0 * s)

        def score(shape: Array) -> tuple[Array, Array]:
            value = np.log(shape) - special.digamma(shape) - s  # decreasing in the shape
            return value, 1.0 / shape - special.polygamma(1, shape)

        a, converged = _safeguarded_newton(
            score, a, np.full(rows, 1e-6), np.full(rows, 1e12), increasing=False
        )
        return a, mean / a, ok & converged
    if family == WEIBULL:
        peak = x.max(axis=1)
        z = x / peak[:, None]
        lz = np.log(z)
        lz_mean = lz.mean(axis=1)

        def score(shape: Array) -> tuple[Array, Array]:
            w = z ** shape[:, None]
            s0 = w.sum(axis=1)
            s1 = (w * lz).sum(axis=1)
            s2 = (w * lz * lz).sum(axis=1)
            value = s1 / s0 - 1.0 / shape - lz_mean  # increasing in the shape
            return value, s2 / s0 - (s1 / s0) ** 2 + 1.0 / shape**2

        spread = lz.std(axis=1)
        start = np.where(spread > 0, math.pi / (math.sqrt(6.0) * np.maximum(spread, 1e-12)), 1.0)
        c, converged = _safeguarded_newton(
            score, start, np.full(rows, 1e-3), np.full(rows, 1e4), increasing=True
        )
        scale = peak * ((z ** c[:, None]).mean(axis=1)) ** (1.0 / c)
        return c, scale, (spread > 0) & converged
    # Pareto II: the generalised Pareto with xi > 0
    xi, sigma, _, boundary = gpd.fit_matrix(x, positive_only=True)
    return 1.0 / xi, sigma / xi, ~boundary & np.isfinite(xi) & (xi > 0)


def _start(family: str, x: Array) -> Array:
    a, b, _ = mle_matrix(family, x[None, :])
    return np.array([a[0], b[0]])


def _truncated_negative_loglik(
    family: str, x: Array, truncation: float
) -> Callable[[Array], float]:
    n = len(x)

    def negative(theta: Array) -> float:
        a, b = float(theta[0]), float(theta[1])
        if b <= 0 or (family != LOGNORMAL and a <= 0):
            return math.inf
        with np.errstate(invalid="ignore", divide="ignore"):
            tail = float(sf(family, np.array([truncation]), a, b)[0])
            if not tail > 0:
                return math.inf
            value = float(logpdf(family, x, a, b).sum()) - n * math.log(tail)
        return -value if np.isfinite(value) else math.inf

    return negative


def mle(family: str, x: Array, truncation: float = 0.0) -> tuple[float, float, bool]:
    """Maximum-likelihood (a, b) of one sample; `truncation` d > 0 conditions on X > d."""
    x = np.asarray(x, dtype=np.float64)
    if truncation <= 0.0:
        a, b, ok = mle_matrix(family, x[None, :])
        return float(a[0]), float(b[0]), bool(ok[0])
    start = _start(family, x)
    negative = _truncated_negative_loglik(family, x, truncation)
    if family == LOGNORMAL:
        # work with log sigma so that the search never leaves the parameter space
        def wrapped(t: Array) -> float:
            return negative(np.array([t[0], math.exp(t[1])]))

        origin = np.array([start[0], math.log(max(start[1], 1e-12))])
    else:

        def wrapped(t: Array) -> float:
            return negative(np.exp(t))

        origin = np.log(np.maximum(start, 1e-12))
    found = optimize.minimize(
        wrapped,
        origin,
        method="Nelder-Mead",
        options={"xatol": 1e-11, "fatol": 1e-12, "maxiter": 4000},
    )
    if family == LOGNORMAL:
        a, b = float(found.x[0]), math.exp(float(found.x[1]))
        inside = EDGE[0] < b < EDGE[1]
    else:
        a, b = math.exp(float(found.x[0])), math.exp(float(found.x[1]))
        inside = EDGE[0] < a < EDGE[1] and b < EDGE[1] * 1e3
    return a, b, bool(found.success and np.isfinite(found.fun) and inside)


def loglik(family: str, x: Array, a: float, b: float, truncation: float = 0.0) -> float:
    """Log-likelihood, conditioned on X > d when `truncation` is positive."""
    x = np.asarray(x, dtype=np.float64)
    value = float(logpdf(family, x, a, b).sum())
    if truncation > 0.0:
        value -= len(x) * math.log(float(sf(family, np.array([truncation]), a, b)[0]))
    return value


@dataclass(frozen=True)
class Estimate:
    family: str
    a: float
    b: float
    loglik: float
    n: int
    converged: bool
    a_se: float
    b_se: float
    truncation: float = 0.0

    @property
    def parameters(self) -> tuple[float, float]:
        return self.a, self.b

    @property
    def aic(self) -> float:
        return 4.0 - 2.0 * self.loglik

    @property
    def bic(self) -> float:
        return 2.0 * math.log(self.n) - 2.0 * self.loglik


def estimate(family: str, x: Array, truncation: float = 0.0) -> Estimate:
    """Maximum likelihood with standard errors from the observed information (numerical Hessian
    of the log-likelihood in the parameters of the family)."""
    x = np.asarray(x, dtype=np.float64)
    a, b, ok = mle(family, x, truncation)
    value = loglik(family, x, a, b, truncation)
    a_se = b_se = math.nan
    if ok and np.isfinite(value):
        negative = _truncated_negative_loglik(family, x, truncation)
        se = standard_errors(numerical_hessian(negative, np.array([a, b])))
        a_se, b_se = float(se[0]), float(se[1])
    return Estimate(
        family, a, b, value, len(x), ok and bool(np.isfinite(value)), a_se, b_se, truncation
    )


def sample(
    family: str,
    a: Array,
    b: Array,
    size: int,
    rng: np.random.Generator,
    truncation: float = 0.0,
) -> Array:
    """One row of `size` draws for each (a, b); with a truncation point, draws from the
    distribution conditioned on X > d."""
    a = np.asarray(a, dtype=np.float64)[:, None]
    b = np.asarray(b, dtype=np.float64)[:, None]
    rows = a.shape[0]
    if truncation <= 0.0:
        if family == LOGNORMAL:
            return np.exp(a + b * rng.standard_normal((rows, size)))
        if family == GAMMA:
            return rng.gamma(a, b, size=(rows, size))
    u = rng.random((rows, size))
    if truncation > 0.0:
        floor = cdf(family, np.array([truncation]), a, b)
        u = floor + u * (1.0 - floor)
    return np.maximum(ppf(family, u, a, b), np.finfo(float).tiny)
