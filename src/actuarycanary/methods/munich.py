"""Munich chain ladder (MT12): paid and incurred projected together (Quarg and Mack 2004).

Each age-to-age factor of the paid (incurred) triangle is corrected by how far the origin's
incurred-to-paid (paid-to-incurred) ratio lies from its column average, scaled by the Mack
variance parameters and by the correlation lambda fitted on the residuals. The regressions for
lambda leave out the last link (decision 0607). Tail 1, as in the Mack model.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from actuarycanary.methods.assumptions import column_label
from actuarycanary.methods.chain_ladder import Average, ChainLadder, Skipped, chain_ladder
from actuarycanary.methods.diagnostics import WARNING, Diagnostic
from actuarycanary.methods.mack import sigma_squared

MIN_ORIGINS = 5  # MT12


@dataclass(frozen=True)
class Munich:
    paid_chain: ChainLadder  # volume-weighted, all diagonals, tail 1
    incurred_chain: ChainLadder
    sigma_paid: np.ndarray  # per link column
    sigma_incurred: np.ndarray
    ratio: np.ndarray  # Q = P / I per cell, NaN where not defined
    ratio_mean: np.ndarray  # q(j) per column
    rho_paid: np.ndarray  # of Q^-1, per column
    rho_incurred: np.ndarray  # of Q, per column
    residuals_paid: np.ndarray  # r^P per link cell in the regression, NaN elsewhere
    ratio_residuals_paid: np.ndarray  # q^P, likewise
    residuals_incurred: np.ndarray
    ratio_residuals_incurred: np.ndarray
    pairs_paid: np.ndarray  # bool per link cell: in the regression for lambda^P
    pairs_incurred: np.ndarray
    lambda_paid: float
    lambda_incurred: float
    projected_paid: np.ndarray  # observed cells kept, later cells projected jointly
    projected_incurred: np.ndarray
    diagnostics: tuple[Diagnostic, ...]

    @property
    def n_pairs(self) -> tuple[int, int]:
        """Residual pairs behind lambda^P and lambda^I."""
        return int(self.pairs_paid.sum()), int(self.pairs_incurred.sum())

    @property
    def paid_ultimate(self) -> np.ndarray:
        return self.projected_paid[:, -1]

    @property
    def incurred_ultimate(self) -> np.ndarray:
        return self.projected_incurred[:, -1]

    @property
    def projected_ratios(self) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            return self.projected_paid / self.projected_incurred

    @property
    def paid_incurred_gap(self) -> dict[str, np.ndarray]:
        """Incurred minus paid ultimate per origin, Munich against the separate chain ladders."""
        return {
            "munich": self.incurred_ultimate - self.paid_ultimate,
            "chain_ladder": self.incurred_chain.ultimate - self.paid_chain.ultimate,
        }


def _extrapolate(variance: np.ndarray) -> np.ndarray:
    """Columns without an estimate, as in MT06: min(v(j-1)^2 / v(j-2), v(j-2), v(j-1))."""
    variance = variance.copy()
    for j in np.flatnonzero(np.isnan(variance)):
        if j >= 2 and np.isfinite(variance[j - 1]) and np.isfinite(variance[j - 2]):
            previous, before = variance[j - 1], variance[j - 2]
            ratio = previous**2 / before if before > 0 else np.inf
            variance[j] = min(ratio, previous, before)
        elif j >= 1:
            variance[j] = variance[j - 1]
    return variance


def _ratio_variances(weight: np.ndarray, deviation: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """rho^2(j) = sum of weight x deviation^2 / (n(j) - 1) over the valid cells of column j."""
    variance = np.full(weight.shape[1], np.nan)
    for j in range(weight.shape[1]):
        rows = valid[:, j]
        if rows.sum() >= 2:
            variance[j] = float((weight[rows, j] * deviation[rows, j] ** 2).sum()) / (
                rows.sum() - 1
            )
    return _extrapolate(variance)


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    """Least-squares slope through the origin."""
    denominator = float((x**2).sum())
    return float((x * y).sum()) / denominator if denominator > 0 else 0.0


def munich_chain_ladder(
    paid: np.ndarray,
    incurred: np.ndarray,
    *,
    calendar: np.ndarray | None = None,
    min_origins: int = MIN_ORIGINS,
    ages: Sequence[int] | None = None,
    origins: Sequence[str] | None = None,
    lambdas: tuple[float, float] | None = None,
) -> Munich | Skipped:
    """MT12 on cumulative paid and incurred triangles on the same grid (NaN where not observed).

    `lambdas` (paid, incurred) replaces the fitted correlations, for the property that zero
    gives the separate chain ladders."""
    paid = np.asarray(paid, dtype=float)
    incurred = np.asarray(incurred, dtype=float)
    if paid.shape != incurred.shape or not (np.isnan(paid) == np.isnan(incurred)).all():
        raise ValueError("paid and incurred triangles must be observed on the same cells")
    n_origins, n_dev = paid.shape
    if n_origins < min_origins:
        return Skipped("MT12", f"Munich chain ladder needs at least {min_origins} origin periods")
    chains: list[ChainLadder] = []
    for triangle in (paid, incurred):
        chain = chain_ladder(triangle, average=Average.VOLUME_WEIGHTED, calendar=calendar)
        if isinstance(chain, Skipped):
            return Skipped("MT12", chain.reason)
        chains.append(chain)
    paid_chain, incurred_chain = chains
    ages = list(ages) if ages is not None else list(range(n_dev))
    labels = list(origins) if origins is not None else [str(i) for i in range(n_origins)]
    diagnostics: list[Diagnostic] = []

    sigma_p, sigma_i = (
        np.sqrt(sigma_squared(t, c.link_ratios, c.used, c.factors)[0])
        for t, c in ((paid, paid_chain), (incurred, incurred_chain))
    )

    observed = ~np.isnan(paid)
    zero_incurred = observed & (incurred == 0) & (paid > 0)
    for i, j in zip(*np.nonzero(zero_incurred), strict=True):
        diagnostics.append(
            Diagnostic(
                "MT12",
                "ZERO_INCURRED",
                WARNING,
                f"origin {labels[i]} at {ages[j]} months: incurred is zero with paid "
                f"{paid[i, j]:,.2f}; the cell is left out of the residuals",
                f"{labels[i]}:{ages[j]}",
                float(paid[i, j]),
            )
        )
    valid_i = observed & (incurred > 0)  # Q defined
    valid_p = valid_i & (paid > 0)  # Q^-1 defined
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(valid_i, paid / incurred, np.nan)
        q = np.array(
            [
                paid[valid_i[:, j], j].sum() / incurred[valid_i[:, j], j].sum()
                if valid_i[:, j].any()
                else np.nan
                for j in range(n_dev)
            ]
        )
        rho_i = np.sqrt(_ratio_variances(np.where(valid_i, incurred, 0), ratio - q, valid_i))
        rho_p = np.sqrt(_ratio_variances(np.where(valid_p, paid, 0), 1 / ratio - 1 / q, valid_p))
        r_p = (paid_chain.link_ratios - paid_chain.factors) / sigma_p * np.sqrt(paid[:, :-1])
        r_i = (
            (incurred_chain.link_ratios - incurred_chain.factors)
            / sigma_i
            * np.sqrt(incurred[:, :-1])
        )
        q_p = (1 / ratio[:, :-1] - 1 / q[:-1]) / rho_p[:-1] * np.sqrt(paid[:, :-1])
        q_i = (ratio[:, :-1] - q[:-1]) / rho_i[:-1] * np.sqrt(incurred[:, :-1])
    pairs_p = valid_p[:, :-1] & paid_chain.used & np.isfinite(r_p) & np.isfinite(q_p)
    pairs_i = valid_i[:, :-1] & incurred_chain.used & np.isfinite(r_i) & np.isfinite(q_i)
    pairs_p[:, -1] = pairs_i[:, -1] = False  # the last link is left out (decision 0607)
    if lambdas is None:
        lambda_p = _slope(q_p[pairs_p], r_p[pairs_p])
        lambda_i = _slope(q_i[pairs_i], r_i[pairs_i])
    else:
        lambda_p, lambda_i = lambdas

    correct_p = np.zeros(n_dev - 1)
    correct_i = np.zeros(n_dev - 1)
    for j in range(n_dev - 1):
        if not (rho_p[j] > 0 and rho_i[j] > 0):
            diagnostics.append(
                Diagnostic(
                    "MT12",
                    "ZERO_RATIO_VARIANCE",
                    WARNING,
                    f"paid-to-incurred ratios at {ages[j]} months do not vary (or cannot be "
                    f"estimated); the correction of column {column_label(ages, j)} is set to zero",
                    column_label(ages, j),
                )
            )
            continue
        correct_p[j] = lambda_p * sigma_p[j] / rho_p[j]
        correct_i[j] = lambda_i * sigma_i[j] / rho_i[j]

    projected_p = paid.copy()
    projected_i = incurred.copy()
    latest_index = paid_chain.latest_index
    for i in range(n_origins):
        for j in range(latest_index[i], n_dev - 1):
            p, c = projected_p[i, j], projected_i[i, j]
            if p > 0 and c > 0:
                fp = paid_chain.factors[j] + correct_p[j] * (c / p - 1 / q[j])
                fi = incurred_chain.factors[j] + correct_i[j] * (p / c - q[j])
            else:  # no ratio to correct by
                fp, fi = paid_chain.factors[j], incurred_chain.factors[j]
            projected_p[i, j + 1] = p * fp
            projected_i[i, j + 1] = c * fi

    return Munich(
        paid_chain=paid_chain,
        incurred_chain=incurred_chain,
        sigma_paid=sigma_p,
        sigma_incurred=sigma_i,
        ratio=ratio,
        ratio_mean=q,
        rho_paid=rho_p,
        rho_incurred=rho_i,
        residuals_paid=np.where(pairs_p, r_p, np.nan),
        ratio_residuals_paid=np.where(pairs_p, q_p, np.nan),
        residuals_incurred=np.where(pairs_i, r_i, np.nan),
        ratio_residuals_incurred=np.where(pairs_i, q_i, np.nan),
        pairs_paid=pairs_p,
        pairs_incurred=pairs_i,
        lambda_paid=lambda_p,
        lambda_incurred=lambda_i,
        projected_paid=projected_p,
        projected_incurred=projected_i,
        diagnostics=tuple(diagnostics),
    )
