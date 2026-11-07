"""Separation method (MT15): average paid per claim split into a development pattern and a
calendar-period index (Taylor 1977).

Expected incremental paid of origin i in development j is n(i) r(j) lambda(i + j). The pattern
sums to 1 over the observed columns, so the method carries no tail (decision 0618); a tail is
applied outside it, to the ultimates, as selected in the assumptions register. The future index
follows a log-linear trend of the last diagonals or an assumed rate per period.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from actuarycanary.methods.chain_ladder import Skipped

TREND_PERIODS = 5  # MT15
NO_TAIL_LABEL = "no development after the last column (separation method)"


class FutureIndex(StrEnum):
    TREND = "trend"
    ASSUMPTION = "assumption"


@dataclass(frozen=True)
class Separation:
    claim_counts: np.ndarray  # n(i)
    per_claim: np.ndarray  # s(i, j) = X(i, j) / n(i), NaN where not observed
    diagonal_sums: np.ndarray  # d(k)
    column_sums: np.ndarray  # v(j)
    pattern: np.ndarray  # r(j), sums to 1
    index: np.ndarray  # lambda(k), past diagonals k = 0..I-1 then the future ones k = I..2I-2
    growth: float  # per period of the future index: fitted trend or the assumption
    future_index: FutureIndex
    trend_periods: int  # diagonals the trend was fitted on (0 for an assumption)
    projected: np.ndarray  # n r lambda for future cells, NaN for observed ones
    latest: np.ndarray  # cumulative paid C(i, J_i)
    residuals: np.ndarray  # X / (n r lambda) - 1 on observed cells
    period_months: int

    @property
    def n_past(self) -> int:
        return len(self.pattern)

    @property
    def reserve(self) -> np.ndarray:
        return np.nansum(self.projected, axis=1)

    @property
    def ultimate(self) -> np.ndarray:
        return self.latest + self.reserve

    @property
    def implied_rates(self) -> np.ndarray:
        """Annual rate implied by lambda(k) / lambda(k - 1), for k = 1.. (past and future)."""
        return (self.index[1:] / self.index[:-1]) ** (12 / self.period_months) - 1

    @property
    def tail_label(self) -> str:
        return NO_TAIL_LABEL

    def residuals_by(self) -> dict[str, np.ndarray]:
        """Mean residual per origin, development column and past diagonal (diagnostic)."""
        n = self.n_past
        diagonals = np.add.outer(np.arange(n), np.arange(n))
        defined = np.isfinite(self.residuals)
        return {
            "origin": np.array([self.residuals[i, defined[i]].mean() for i in range(n)]),
            "development": np.array([self.residuals[defined[:, j], j].mean() for j in range(n)]),
            "diagonal": np.array(
                [self.residuals[defined & (diagonals == k)].mean() for k in range(n)]
            ),
        }

    def inflation_comparison(self, reference: Mapping[int, float]) -> list[dict[str, float]]:
        """Implied annual rate of each past diagonal k >= 1 against a reference rate (for
        example CPI by calendar period, CV02), where one is given for k."""
        rates = self.implied_rates
        return [
            {"diagonal": float(k), "implied": float(rates[k - 1]), "reference": reference[k]}
            for k in range(1, self.n_past)
            if k in reference
        ]


def _square_triangle(incremental: np.ndarray) -> bool:
    n_origins, n_dev = incremental.shape
    if n_origins != n_dev:
        return False
    upper = np.add.outer(np.arange(n_origins), np.arange(n_dev)) <= n_origins - 1
    return bool((np.isfinite(incremental) == upper).all())


def separation(
    incremental: np.ndarray,
    claim_counts: Sequence[float] | np.ndarray,
    *,
    future_index: FutureIndex = FutureIndex.TREND,
    rate: float | None = None,
    trend_periods: int = TREND_PERIODS,
    period_months: int = 12,
) -> Separation | Skipped:
    """MT15 on an incremental paid triangle (square, NaN after the latest diagonal) and n(i).

    With `future_index` ASSUMPTION, `rate` is the assumed annual rate of the index."""
    x = np.asarray(incremental, dtype=float)
    n = np.asarray(claim_counts, dtype=float)
    if not _square_triangle(x):
        return Skipped("MT15", "separation needs equal origin and development periods")
    size = x.shape[0]
    if len(n) != size or not (np.isfinite(n) & (n > 0)).all():
        return Skipped("MT15", "separation needs claim counts per origin")
    if future_index is FutureIndex.ASSUMPTION and (rate is None or rate <= -1):
        raise ValueError(f"an assumed future index needs a rate above -100 per cent, not {rate}")

    s = x / n[:, None]
    diagonals = np.add.outer(np.arange(size), np.arange(size))
    observed = np.isfinite(s)
    d = np.array([s[observed & (diagonals == k)].sum() for k in range(size)])
    v = np.nansum(s, axis=0)
    lam = np.zeros(size)
    r = np.zeros(size)
    lam[size - 1] = d[size - 1]
    for j in range(size - 1, -1, -1):
        r[j] = v[j] / lam[j:].sum()
        if j:
            denominator = 1 - r[j:].sum()
            if denominator <= 0:
                return Skipped(
                    "MT15", f"the pattern leaves nothing for diagonal {j - 1} (1 - sum of r <= 0)"
                )
            lam[j - 1] = d[j - 1] / denominator

    if future_index is FutureIndex.TREND:
        used = min(trend_periods, size)
        window = lam[size - used :]
        if not (window > 0).all():
            return Skipped("MT15", "the calendar index is not positive on the trend diagonals")
        k = np.arange(size - used, size, dtype=float)
        growth = float(np.exp(np.polyfit(k, np.log(window), 1)[0]) - 1) if used >= 2 else 0.0
    else:
        assert rate is not None
        used = 0
        growth = float((1 + rate) ** (period_months / 12) - 1)
    future = lam[size - 1] * (1 + growth) ** np.arange(1, size)
    index = np.concatenate([lam, future])

    expected = n[:, None] * r[None, :] * index[diagonals]
    projected = np.where(observed, np.nan, expected)
    with np.errstate(divide="ignore", invalid="ignore"):
        residuals = np.where(observed, x / expected - 1, np.nan)
    latest = np.array([x[i, : size - i].sum() for i in range(size)])
    return Separation(
        claim_counts=n,
        per_claim=s,
        diagonal_sums=d,
        column_sums=v,
        pattern=r,
        index=index,
        growth=growth,
        future_index=FutureIndex(future_index),
        trend_periods=used,
        projected=projected,
        latest=latest,
        residuals=residuals,
        period_months=period_months,
    )
