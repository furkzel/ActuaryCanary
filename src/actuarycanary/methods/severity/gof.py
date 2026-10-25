"""Goodness of fit for MT17: Kolmogorov-Smirnov D and Anderson-Darling A^2 with p-values by
parametric bootstrap (the parameters are estimated, so the usual tables do not apply), and the
data of the quantile-quantile and probability plots.

With a truncation point d > 0, D and A^2 use the conditional distribution function
(F(x) - F(d)) / (1 - F(d)) (record 0615).
"""

from dataclasses import dataclass

import numpy as np

from actuarycanary.methods.severity import families as fam

QQ_POINTS = 200  # probability levels of the plot data
TINY = 1e-300


@dataclass(frozen=True)
class Gof:
    ks: float
    ad: float
    ks_p: float
    ad_p: float
    n_used: int  # claims behind D, A^2 and the p-values
    n_boot: int  # bootstrap samples that were refitted successfully


def statistics(
    family: str, x_sorted: np.ndarray, a: np.ndarray, b: np.ndarray, truncation: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    """D and A^2 of each row of ascending `x_sorted` (B, n) against its own (a, b)."""
    n = x_sorted.shape[1]
    a, b = np.asarray(a, dtype=np.float64)[:, None], np.asarray(b, dtype=np.float64)[:, None]
    big_f = fam.cdf(family, x_sorted, a, b)
    big_s = fam.sf(family, x_sorted, a, b)
    if truncation > 0.0:
        floor = fam.cdf(family, np.array([truncation]), a, b)
        keep = fam.sf(family, np.array([truncation]), a, b)
        big_f = np.clip((big_f - floor) / keep, 0.0, 1.0)
        big_s = np.clip(big_s / keep, 0.0, 1.0)
    index = np.arange(1, n + 1)[None, :]
    d_plus = (index / n - big_f).max(axis=1)
    d_minus = (big_f - (index - 1) / n).max(axis=1)
    ks = np.maximum(d_plus, d_minus)
    weights = 2.0 * index - 1.0
    ad = (
        -n
        - (
            weights * (np.log(np.maximum(big_f, TINY)) + np.log(np.maximum(big_s, TINY))[:, ::-1])
        ).sum(axis=1)
        / n
    )
    return ks, ad


def goodness_of_fit(
    family: str,
    x: np.ndarray,
    a: float,
    b: float,
    n_boot: int,
    rng: np.random.Generator,
    truncation: float = 0.0,
) -> Gof:
    """D, A^2 and bootstrap p-values of sample `x` against the fitted (a, b).

    Samples are drawn from the fitted distribution (conditioned on X > d under truncation),
    refitted by maximum likelihood, and their statistics taken against their own refit. The
    p-value is (1 + number of bootstrap statistics at or above the observed) / (B + 1)."""
    x = np.sort(np.asarray(x, dtype=np.float64))
    n = len(x)
    ks, ad = (
        v[0] for v in statistics(family, x[None, :], np.array([a]), np.array([b]), truncation)
    )
    if n_boot <= 0:
        return Gof(float(ks), float(ad), float("nan"), float("nan"), n, 0)
    draws = fam.sample(family, np.full(n_boot, a), np.full(n_boot, b), n, rng, truncation)
    if truncation > 0.0:
        refit = [fam.mle(family, row, truncation) for row in draws]
        a_boot = np.array([r[0] for r in refit])
        b_boot = np.array([r[1] for r in refit])
        ok = np.array([r[2] for r in refit])
    else:
        a_boot, b_boot, ok = fam.mle_matrix(family, draws)
    ok &= np.isfinite(a_boot) & np.isfinite(b_boot)
    boot_ks, boot_ad = statistics(
        family, np.sort(draws[ok], axis=1), a_boot[ok], b_boot[ok], truncation
    )
    used = int(ok.sum())
    return Gof(
        float(ks),
        float(ad),
        (1 + int(np.sum(boot_ks >= ks))) / (used + 1),
        (1 + int(np.sum(boot_ad >= ad))) / (used + 1),
        n,
        used,
    )


def plot_data(
    family: str, x: np.ndarray, a: float, b: float, truncation: float = 0.0, points: int = QQ_POINTS
) -> dict[str, np.ndarray]:
    """Data of the quantile-quantile, probability-probability and tail (survival, log scale)
    plots of one fitted family: at `points` probability levels (j - 1/2) / points, the empirical
    quantile (Hazen rule, which is the order statistic when points equals n), the fitted
    quantile, the fitted distribution function at the empirical quantile, and the empirical and
    fitted survival there."""
    x = np.asarray(x, dtype=np.float64)
    m = min(points, len(x))
    probability = (np.arange(1, m + 1) - 0.5) / m
    empirical = np.quantile(x, probability, method="hazen")
    floor = float(fam.cdf(family, np.array([truncation]), a, b)[0]) if truncation > 0 else 0.0
    fitted = fam.ppf(family, floor + probability * (1.0 - floor), a, b)
    keep = 1.0 - floor
    fitted_survival = fam.sf(family, empirical, a, b) / keep
    return {
        "probability": probability,
        "empirical_quantile": empirical,
        "fitted_quantile": np.asarray(fitted),
        "fitted_cdf": 1.0 - fitted_survival,
        "empirical_survival": 1.0 - probability,
        "fitted_survival": fitted_survival,
    }
