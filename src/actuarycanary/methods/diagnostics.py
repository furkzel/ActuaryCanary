"""Diagnostics of the triangle methods as data, for the report to draw.

Tables: factor stability per column (MT02), standardised residuals by origin, column and
diagonal (MT02, MT06) and the averages side by side (MT02). Warnings: thin evidence (every
method), late development with tail 1, factors resting on few origins or on a zero
denominator (MT02), and negative IBNR (paid ultimate below incurred to date).
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from actuarycanary.methods.assumptions import cell_label, column_label
from actuarycanary.methods.chain_ladder import Average, ChainLadder, Skipped, chain_ladder
from actuarycanary.methods.mack import sigma_squared, standardised_residuals

THIN_EVIDENCE_ORIGINS = 8  # fewer origin periods: thin evidence, said in every method
LATE_DEVELOPMENT_FACTOR = 1.05  # last factor above it with tail 1: ultimates may be short
FEW_LINK_RATIOS = 3  # a factor resting on fewer origins is flagged
COMPARISON_DIAGONALS = 3  # the latest-n average shown next to the others
WARNING = "WARNING"


@dataclass(frozen=True)
class Diagnostic:
    method: str  # specification ID
    code: str
    severity: str
    message: str
    target: str = ""  # origin, column or cell, as in the assumptions register
    value: float | None = None


@dataclass(frozen=True)
class FactorStability:
    """Per development column: link ratios used and their spread, next to the factors."""

    columns: tuple[str, ...]
    used: np.ndarray  # number of link ratios in the average
    mean: np.ndarray
    standard_deviation: np.ndarray
    coefficient_of_variation: np.ndarray
    minimum: np.ndarray
    maximum: np.ndarray
    average: np.ndarray  # the MT02 average before selection
    selected: np.ndarray


@dataclass(frozen=True)
class Residuals:
    """Standardised link-ratio residuals and their mean per origin, column and diagonal."""

    values: np.ndarray  # origins x columns, NaN where not defined
    by_origin: np.ndarray
    by_column: np.ndarray
    by_diagonal: dict[int, float]  # calendar index of the later cell: mean residual


@dataclass(frozen=True)
class ChainLadderDiagnostics:
    stability: FactorStability
    residuals: Residuals
    averages: dict[str, np.ndarray]  # name: factor per column
    warnings: tuple[Diagnostic, ...]


def thin_evidence(method: str, n_origins: int, what: str = "origin periods") -> Diagnostic | None:
    if n_origins >= THIN_EVIDENCE_ORIGINS:
        return None
    return Diagnostic(
        method,
        "THIN_EVIDENCE",
        WARNING,
        f"only {n_origins} {what}: thin evidence; factors, ratios and ranges rest on few "
        f"observations (fewer than {THIN_EVIDENCE_ORIGINS})",
        value=float(n_origins),
    )


def factor_stability(chain: ChainLadder, ages: Sequence[int]) -> FactorStability:
    n_columns = len(chain.factors)
    stats = np.full((5, n_columns), np.nan)
    used = np.zeros(n_columns, dtype=np.int64)
    for j in range(n_columns):
        ratios = chain.link_ratios[chain.used[:, j] & np.isfinite(chain.link_ratios[:, j]), j]
        used[j] = len(ratios)
        if len(ratios):
            sd = float(ratios.std(ddof=1)) if len(ratios) > 1 else np.nan
            mean = float(ratios.mean())
            stats[:, j] = (mean, sd, sd / mean if mean else np.nan, ratios.min(), ratios.max())
    return FactorStability(
        tuple(column_label(ages, j) for j in range(n_columns)),
        used,
        stats[0],
        stats[1],
        stats[2],
        stats[3],
        stats[4],
        chain.averages,
        chain.factors,
    )


def residuals(chain: ChainLadder, cumulative: np.ndarray, calendar: np.ndarray | None) -> Residuals:
    sigma2, _, _ = sigma_squared(cumulative, chain.link_ratios, chain.used, chain.factors)
    values = standardised_residuals(
        cumulative, chain.link_ratios, chain.used, chain.factors, sigma2
    )
    n_origins, n_dev = cumulative.shape
    diagonals = (
        np.add.outer(np.arange(n_origins), np.arange(n_dev)) if calendar is None else calendar
    )[:, 1:]
    defined = np.isfinite(values)
    with np.errstate(invalid="ignore"):
        by_origin = np.array([np.nanmean(r) if np.isfinite(r).any() else np.nan for r in values])
        by_column = np.array([np.nanmean(c) if np.isfinite(c).any() else np.nan for c in values.T])
    by_diagonal = {
        int(d): float(values[defined & (diagonals == d)].mean())
        for d in np.unique(diagonals[defined])
    }
    return Residuals(values, by_origin, by_column, by_diagonal)


def compare_averages(
    cumulative: np.ndarray, calendar: np.ndarray | None, latest_n: int = COMPARISON_DIAGONALS
) -> dict[str, np.ndarray]:
    """Volume-weighted, simple and latest-n volume-weighted factors for comparison (MT02)."""
    options = {"min_origins": 1, "calendar": calendar}
    runs = {
        "volume_weighted": chain_ladder(cumulative, **options),
        "simple": chain_ladder(cumulative, average=Average.SIMPLE, **options),
        f"volume_weighted_latest_{latest_n}": chain_ladder(
            cumulative, n_diagonals=latest_n, **options
        ),
    }
    return {name: r.factors for name, r in runs.items() if isinstance(r, ChainLadder)}


def chain_ladder_warnings(
    chain: ChainLadder,
    cumulative: np.ndarray,
    origins: Sequence[str],
    ages: Sequence[int],
    method: str = "MT02",
) -> list[Diagnostic]:
    warnings: list[Diagnostic] = []
    thin = thin_evidence(method, len(origins))
    if thin:
        warnings.append(thin)
    n_columns = len(chain.factors)
    counts = chain.used.sum(axis=0)
    estimated = [j for j in range(n_columns) if counts[j] > 0]
    if estimated and chain.tail_factor == 1.0:
        last = estimated[-1]
        if chain.factors[last] > LATE_DEVELOPMENT_FACTOR:
            warnings.append(
                Diagnostic(
                    method,
                    "LATE_DEVELOPMENT",
                    WARNING,
                    f"development from {ages[last]} to {ages[last + 1]} months is still "
                    f"{chain.factors[last]:.4g} and the tail factor is 1.0, so ultimates may "
                    "be understated; a tail factor can be set in the assumptions register",
                    column_label(ages, last),
                    float(chain.factors[last]),
                )
            )
    for j in estimated:
        if counts[j] < FEW_LINK_RATIOS:
            warnings.append(
                Diagnostic(
                    method,
                    "FEW_LINK_RATIOS",
                    WARNING,
                    f"factor {column_label(ages, j)} ({chain.factors[j]:.4g}) rests on "
                    f"{counts[j]} origin{'s' if counts[j] != 1 else ''}, fewer than "
                    f"{FEW_LINK_RATIOS}",
                    column_label(ages, j),
                    float(counts[j]),
                )
            )
        zero = chain.used[:, j] & (cumulative[:, j] == 0) & (cumulative[:, j + 1] != 0)
        for i in (int(k) for k in np.flatnonzero(zero)):
            others = chain.used[:, j].copy()
            others[i] = False
            denominator = float(cumulative[others, j].sum())
            without = (
                float(cumulative[others, j + 1].sum()) / denominator if denominator else np.nan
            )
            warnings.append(
                Diagnostic(
                    method,
                    "ZERO_DENOMINATOR",
                    WARNING,
                    f"factor {column_label(ages, j)} is {chain.factors[j]:.4g}: origin "
                    f"{origins[i]} has 0 at {ages[j]} months and {cumulative[i, j + 1]:,.2f} "
                    f"at {ages[j + 1]} months, so it adds to the numerator only; without that "
                    f"cell the factor is {without:.4g}. The cell is kept by default (MT02); "
                    f"exclude cell {cell_label(origins[i], ages, j)} in the assumptions "
                    "register to leave it out",
                    cell_label(origins[i], ages, j),
                    without,
                )
            )
    return warnings


def chain_ladder_diagnostics(
    chain: ChainLadder,
    cumulative: np.ndarray,
    origins: Sequence[str],
    ages: Sequence[int],
    calendar: np.ndarray | None = None,
    method: str = "MT02",
) -> ChainLadderDiagnostics:
    cumulative = np.asarray(cumulative, dtype=float)
    return ChainLadderDiagnostics(
        factor_stability(chain, ages),
        residuals(chain, cumulative, calendar),
        compare_averages(cumulative, calendar),
        tuple(chain_ladder_warnings(chain, cumulative, origins, ages, method)),
    )


def negative_ibnr(
    method: str,
    ultimate: np.ndarray,
    incurred: np.ndarray,
    origins: Sequence[str],
    basis: str = "paid",
) -> list[Diagnostic]:
    """Origins whose ultimate is below the incurred to date (for example a paid ultimate)."""
    found: list[Diagnostic] = []
    for i, origin in enumerate(origins):
        u, c = ultimate[i], incurred[i]
        if np.isfinite(u) and u < c:
            found.append(
                Diagnostic(
                    method,
                    "NEGATIVE_IBNR",
                    WARNING,
                    f"{basis} ultimate of origin {origin} ({u:,.2f}) is below the incurred to "
                    f"date ({c:,.2f}): IBNR {u - c:,.2f}",
                    origin,
                    float(u - c),
                )
            )
    return found


def skipped(result: object, method: str) -> Diagnostic | None:
    """A Skipped result as a diagnostic, so the report can list why a method did not run."""
    if isinstance(result, Skipped):
        return Diagnostic(method, "NOT_RUN", WARNING, result.reason)
    return None
