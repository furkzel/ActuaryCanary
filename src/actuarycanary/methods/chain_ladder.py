"""Chain ladder (MT02): age-to-age factors, cumulative factors, ultimates and projection.

Pure functions on a cumulative triangle given as a 2-D array, origins down and development
indices across, with NaN in cells that are not observed.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

HIGH_LOW_MIN_RATIOS = 5  # exclude_high_low applies to columns with at least this many


class Average(StrEnum):
    VOLUME_WEIGHTED = "volume_weighted"
    SIMPLE = "simple"


@dataclass(frozen=True)
class Skipped:
    """The method did not run; `reason` says why, in words for the report."""

    method: str
    reason: str


@dataclass(frozen=True)
class ChainLadder:
    link_ratios: np.ndarray  # F(i, j) = C(i, j+1) / C(i, j); NaN where not defined
    used: np.ndarray  # bool, link ratio in the average of its column
    factors: np.ndarray  # selected age-to-age factor per column, length J - 1
    tail_factor: float
    cdf: np.ndarray  # cumulative factor to ultimate per development index, length J
    latest: np.ndarray  # C(i, J_i)
    latest_index: np.ndarray  # J_i
    ultimate: np.ndarray
    projected: np.ndarray  # observed cells kept, later cells projected with the factors
    warnings: tuple[str, ...]
    zero_latest: np.ndarray  # bool per origin: ultimate is zero, advise BF (MT02)
    negative: np.ndarray  # bool per origin: negative cumulative values, unreliable
    # the averages before any selected factor replaced them; equal to `factors` without one
    averages: np.ndarray
    overridden: np.ndarray  # bool per column: a selected factor replaced the average

    @property
    def reserve(self) -> np.ndarray:
        """Ultimate minus the latest cumulative value of the same triangle."""
        return self.ultimate - self.latest

    @property
    def cdf_at_latest(self) -> np.ndarray:
        """CDF(J_i) per origin: the pattern that Bornhuetter–Ferguson and Cape Cod use."""
        return self.cdf[self.latest_index]


def _usable(
    observed: np.ndarray,
    calendar: np.ndarray,
    n_diagonals: int | None,
    exclusions: Iterable[tuple[int, int]],
) -> np.ndarray:
    """Usable set A_j as a mask over link-ratio positions (origins x J - 1)."""
    usable = observed[:, 1:] & observed[:, :-1]
    if n_diagonals is not None:
        latest = calendar[observed].max()
        usable &= calendar[:, 1:] > latest - n_diagonals
    for origin, column in exclusions:
        usable[origin, column] = False
    return usable


def _drop_high_low(link_ratios: np.ndarray, usable: np.ndarray) -> np.ndarray:
    usable = usable.copy()
    for j in range(usable.shape[1]):
        rows = np.flatnonzero(usable[:, j] & np.isfinite(link_ratios[:, j]))
        if len(rows) >= HIGH_LOW_MIN_RATIOS:
            values = link_ratios[rows, j]
            usable[rows[np.argmax(values)], j] = False
            usable[rows[np.argmin(values)], j] = False
    return usable


def chain_ladder(
    cumulative: np.ndarray,
    *,
    average: Average = Average.VOLUME_WEIGHTED,
    n_diagonals: int | None = None,
    exclusions: Iterable[tuple[int, int]] = (),
    exclude_high_low: bool = False,
    tail_factor: float = 1.0,
    min_origins: int = 3,
    calendar: np.ndarray | None = None,
    selected: Mapping[int, float] | None = None,
) -> ChainLadder | Skipped:
    """MT02 on `cumulative`. `calendar` gives each cell's valuation point (diagonal); by default
    i + j, the diagonal of a triangle whose origin and development periods are equal.
    `selected` replaces the average of single columns (column index to factor); the averages
    stay in the result as the alternative."""
    cumulative = np.asarray(cumulative, dtype=float)
    n_origins, n_dev = cumulative.shape
    if n_origins < min_origins:
        return Skipped("MT02", f"chain ladder needs at least {min_origins} origin periods")
    observed = ~np.isnan(cumulative)
    diagonals = (
        np.add.outer(np.arange(n_origins), np.arange(n_dev)) if calendar is None else calendar
    )

    with np.errstate(divide="ignore", invalid="ignore"):
        link_ratios = cumulative[:, 1:] / cumulative[:, :-1]
    link_ratios[~(observed[:, 1:] & observed[:, :-1]) | (cumulative[:, :-1] == 0)] = np.nan

    used = _usable(observed, diagonals, n_diagonals, exclusions)
    if average == Average.SIMPLE:  # link ratios with C(i, j) > 0 only
        used &= ~np.isnan(link_ratios) & (np.nan_to_num(cumulative[:, :-1]) > 0)
    if exclude_high_low:
        used = _drop_high_low(link_ratios, used)

    warnings: list[str] = []
    factors = np.ones(n_dev - 1)
    for j in range(n_dev - 1):
        rows = used[:, j]
        if average == Average.SIMPLE:
            if rows.any():
                factors[j] = float(link_ratios[rows, j].mean())
                continue
        else:
            denominator = float(cumulative[rows, j].sum())
            if rows.any() and denominator != 0:
                factors[j] = float(cumulative[rows, j + 1].sum()) / denominator
                continue
        warnings.append(f"development column {j} has no usable link ratio; factor set to 1")

    averages = factors.copy()
    overridden = np.zeros(n_dev - 1, dtype=bool)
    for j, value in (selected or {}).items():
        if not 0 <= j < n_dev - 1 or not np.isfinite(value) or value <= 0:
            raise ValueError(f"selected factor {value} for column {j} is not usable")
        factors[j] = value
        overridden[j] = True

    cdf = np.empty(n_dev)
    cdf[-1] = tail_factor
    for j in range(n_dev - 2, -1, -1):
        cdf[j] = factors[j] * cdf[j + 1]

    latest_index = observed.sum(axis=1) - 1
    latest = cumulative[np.arange(n_origins), latest_index]
    ultimate = latest * cdf[latest_index]

    projected = cumulative.copy()
    for i in range(n_origins):
        for k in range(latest_index[i], n_dev - 1):
            projected[i, k + 1] = projected[i, k] * factors[k]

    return ChainLadder(
        link_ratios=link_ratios,
        used=used,
        factors=factors,
        tail_factor=tail_factor,
        cdf=cdf,
        latest=latest,
        latest_index=latest_index,
        ultimate=ultimate,
        projected=projected,
        warnings=tuple(warnings),
        zero_latest=latest == 0,
        negative=np.any(np.where(observed, cumulative, 0.0) < 0, axis=1),
        averages=averages,
        overridden=overridden,
    )
