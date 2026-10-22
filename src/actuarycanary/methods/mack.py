"""Mack standard error (MT06) and the lognormal reserve range built on it.

The standard error is Mack's (1993) distribution-free one for the chain ladder with
volume-weighted factors over all diagonals, no exclusions and tail 1. Percentiles, value at
risk and tail value at risk assume a lognormal reserve with the Mack mean and standard
error: an approximation, labelled as such wherever it is shown.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

from actuarycanary.methods.chain_ladder import Average, ChainLadder, Skipped, chain_ladder

MIN_SIGMA_COLUMNS = 3  # fewer estimable columns: not run (MT06)
PERCENTILES = (0.5, 0.75, 0.9, 0.95, 0.99, 0.995)
VAR_LEVEL = 0.995
TVAR_LEVEL = 0.99
LOGNORMAL_LABEL = "lognormal approximation with the Mack mean and standard error"
SELECTED_LABEL = "Mack CV applied to selected reserve"


def sigma_squared(
    cumulative: np.ndarray, link_ratios: np.ndarray, used: np.ndarray, factors: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(sigma squared per column, extrapolated mask, link ratios per column).

    A column's estimate uses its usable link ratios with a positive denominator; a column with
    fewer than two is extrapolated from the two before it, or repeats the one before when
    there are fewer than two earlier columns (MT06)."""
    n_columns = len(factors)
    sigma2 = np.full(n_columns, np.nan)
    counts = np.zeros(n_columns, dtype=np.int64)
    for j in range(n_columns):
        rows = used[:, j] & np.isfinite(link_ratios[:, j])
        counts[j] = int(rows.sum())
        if counts[j] >= 2:
            deviation = link_ratios[rows, j] - factors[j]
            sigma2[j] = float((cumulative[rows, j] * deviation**2).sum()) / (counts[j] - 1)
    extrapolated = np.isnan(sigma2)
    for j in range(n_columns):
        if not extrapolated[j]:
            continue
        if j >= 2 and np.isfinite(sigma2[j - 1]) and np.isfinite(sigma2[j - 2]):
            previous, before = sigma2[j - 1], sigma2[j - 2]
            ratio = previous**2 / before if before > 0 else np.inf
            sigma2[j] = min(ratio, previous, before)
        elif j >= 1:
            sigma2[j] = sigma2[j - 1]
    return sigma2, extrapolated, counts


def standardised_residuals(
    cumulative: np.ndarray,
    link_ratios: np.ndarray,
    used: np.ndarray,
    factors: np.ndarray,
    sigma2: np.ndarray,
) -> np.ndarray:
    """(F(i,j) - f(j)) sqrt(C(i,j)) / sigma(j) on usable link ratios; NaN elsewhere."""
    with np.errstate(divide="ignore", invalid="ignore"):
        residuals = (link_ratios - factors) * np.sqrt(cumulative[:, :-1]) / np.sqrt(sigma2)
    keep = used & np.isfinite(link_ratios) & (sigma2 > 0)
    return np.where(keep, residuals, np.nan)


@dataclass(frozen=True)
class LognormalRange:
    """Reserve percentiles, VaR and TVaR of a lognormal with mean `reserve` and `se`."""

    reserve: float
    standard_error: float
    mu: float
    sigma: float
    percentiles: dict[float, float]
    var_level: float
    value_at_risk: float
    tvar_level: float
    tail_value_at_risk: float
    label: str = LOGNORMAL_LABEL


def lognormal_range(
    reserve: float,
    standard_error: float,
    percentiles: Sequence[float] = PERCENTILES,
    var_level: float = VAR_LEVEL,
    tvar_level: float = TVAR_LEVEL,
) -> LognormalRange | None:
    """None when the reserve is not positive or the standard error is zero (MT06)."""
    if not (reserve > 0 and standard_error > 0):
        return None
    sigma2 = float(np.log1p((standard_error / reserve) ** 2))
    sigma = float(np.sqrt(sigma2))
    mu = float(np.log(reserve) - sigma2 / 2)

    def quantile(p: float) -> float:
        return float(np.exp(mu + sigma * norm.ppf(p)))

    z = float(norm.ppf(tvar_level))
    tvar = float(np.exp(mu + sigma2 / 2) * norm.cdf(sigma - z) / (1 - tvar_level))
    return LognormalRange(
        reserve,
        standard_error,
        mu,
        sigma,
        {p: quantile(p) for p in percentiles},
        var_level,
        quantile(var_level),
        tvar_level,
        tvar,
    )


@dataclass(frozen=True)
class Mack:
    chain: ChainLadder  # the Mack chain ladder: volume-weighted, all diagonals, tail 1
    sigma_squared: np.ndarray  # per column
    extrapolated: np.ndarray  # bool per column
    reserve: np.ndarray  # per origin, ultimate minus latest
    standard_error: np.ndarray  # per origin
    total_reserve: float
    total_standard_error: float
    residuals: np.ndarray  # standardised link-ratio residuals, origins x columns

    @property
    def coefficient_of_variation(self) -> np.ndarray:
        """se / reserve per origin; NaN where the reserve is zero."""
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(self.reserve != 0, self.standard_error / self.reserve, np.nan)

    @property
    def total_coefficient_of_variation(self) -> float:
        return self.total_standard_error / self.total_reserve if self.total_reserve else np.nan

    def ranges(
        self,
        percentiles: Sequence[float] = PERCENTILES,
        var_level: float = VAR_LEVEL,
        tvar_level: float = TVAR_LEVEL,
    ) -> tuple[list[LognormalRange | None], LognormalRange | None]:
        """Lognormal range per origin and in total; None where it is not shown (MT06)."""
        per_origin = [
            lognormal_range(float(r), float(s), percentiles, var_level, tvar_level)
            for r, s in zip(self.reserve, self.standard_error, strict=True)
        ]
        total = lognormal_range(
            self.total_reserve, self.total_standard_error, percentiles, var_level, tvar_level
        )
        return per_origin, total


@dataclass(frozen=True)
class SelectedRange:
    """The Mack coefficient of variation applied to a reserve that is not the Mack one."""

    reserve: float
    coefficient_of_variation: float
    standard_error: float
    range: LognormalRange | None
    label: str = SELECTED_LABEL


def applied_to_selected(
    cv: float,
    selected_reserve: float,
    percentiles: Sequence[float] = PERCENTILES,
    var_level: float = VAR_LEVEL,
    tvar_level: float = TVAR_LEVEL,
) -> SelectedRange:
    """se(sel) = cv R(sel), labelled (MT06, record 0011)."""
    se = cv * selected_reserve if np.isfinite(cv) else np.nan
    found = lognormal_range(selected_reserve, se, percentiles, var_level, tvar_level)
    return SelectedRange(selected_reserve, cv, se, found)


def mack(
    cumulative: np.ndarray, *, calendar: np.ndarray | None = None, min_origins: int = 3
) -> Mack | Skipped:
    """MT06 on a cumulative triangle (NaN where not observed)."""
    cumulative = np.asarray(cumulative, dtype=float)
    chain = chain_ladder(
        cumulative, average=Average.VOLUME_WEIGHTED, min_origins=min_origins, calendar=calendar
    )
    if isinstance(chain, Skipped):
        return Skipped("MT06", chain.reason)
    sigma2, extrapolated, _ = sigma_squared(
        cumulative, chain.link_ratios, chain.used, chain.factors
    )
    if int((~extrapolated).sum()) < MIN_SIGMA_COLUMNS:
        return Skipped("MT06", "too few link ratios to estimate variance")

    n_origins, n_dev = cumulative.shape
    f = chain.factors
    sums = np.array([cumulative[chain.used[:, k], k].sum() for k in range(n_dev - 1)])
    with np.errstate(divide="ignore", invalid="ignore"):
        process = np.where(f != 0, sigma2 / f**2, 0.0)
        parameter = np.where(sums > 0, process / sums, 0.0)

    ultimate = chain.ultimate
    mse = np.zeros(n_origins)
    for i in range(n_origins):
        if ultimate[i] == 0:
            continue  # zero latest: nothing to project, flagged by MT02
        columns = range(chain.latest_index[i], n_dev - 1)
        mse[i] = ultimate[i] ** 2 * sum(
            process[k] / chain.projected[i, k] + parameter[k] for k in columns
        )
    covariance = 0.0
    tail_sums = np.concatenate([np.cumsum(parameter[::-1])[::-1], [0.0]])  # sum over k >= index
    for i in range(n_origins):
        for m in range(i + 1, n_origins):
            start = max(chain.latest_index[i], chain.latest_index[m])
            covariance += 2 * ultimate[i] * ultimate[m] * tail_sums[start]
    reserve = chain.reserve
    residuals = standardised_residuals(cumulative, chain.link_ratios, chain.used, f, sigma2)
    return Mack(
        chain=chain,
        sigma_squared=sigma2,
        extrapolated=extrapolated,
        reserve=reserve,
        standard_error=np.sqrt(mse),
        total_reserve=float(reserve.sum()),
        total_standard_error=float(np.sqrt(mse.sum() + covariance)),
        residuals=residuals,
    )
