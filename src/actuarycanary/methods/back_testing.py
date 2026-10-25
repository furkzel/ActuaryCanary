"""Back-testing of past selections (MT22) and the back-test error (AE02).

The methods are re-run on the triangle as known at earlier cut-offs c - h: the cells valued on
or before that point, without the origins that had not started (the as-of rule of CV04, the
same cut as `modules.reserving.truncate_triangle`). Their ultimates are compared with today's
reference per origin: today's selected ultimate, which stands for the actual where the origin
is mature (reported share at least `mature_at`) and is labelled "against today's estimate"
elsewhere. Errors are summarised per method and horizon, weighted by the reference.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from actuarycanary.methods.bornhuetter_ferguson import (
    DATA_DERIVED_PRIOR,
    BornhuetterFerguson,
    bornhuetter_ferguson,
)
from actuarycanary.methods.cape_cod import CapeCod, cape_cod
from actuarycanary.methods.chain_ladder import ChainLadder, Skipped, chain_ladder
from actuarycanary.methods.expected_loss_ratio import expected_loss_ratio
from actuarycanary.methods.mack import Mack, mack
from actuarycanary.methods.odp_bootstrap import OdpBootstrap, odp_bootstrap
from actuarycanary.methods.selection import select_ultimates

HORIZONS_MONTHS = (12, 24, 36)
METHODS = ("MT02", "MT03", "MT04", "MT05", "MT10")
MATURE_AT = 0.95
BACKTEST_SIMULATIONS = 1_000  # decision 0618
MIN_ORIGINS = 3  # fewer origins with a reference: the horizon is not summarised
RANGE = (0.05, 0.95)  # expected share inside: 90 per cent
ACTUAL = "actual"
TODAY = "against today's estimate"

# a method re-run on an as-of triangle: (cumulative, calendar, origin rows kept) -> ultimates
Runner = Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray | Skipped]


@dataclass(frozen=True)
class AsOf:
    """A triangle as known `steps` valuation points before its latest one."""

    steps: int
    cumulative: np.ndarray
    calendar: np.ndarray
    rows: np.ndarray  # bool per origin of today's triangle: started by then
    columns: np.ndarray  # bool per development column of today's triangle


def as_of(cumulative: np.ndarray, calendar: np.ndarray, steps: int) -> AsOf | None:
    """The cells with calendar index at most latest - steps, empty origins and columns removed
    (None when nothing was known then). `calendar` is -1 where a cell is not observed."""
    cumulative = np.asarray(cumulative, dtype=float)
    observed = ~np.isnan(cumulative)
    point = int(calendar[observed].max()) - steps
    keep = observed & (calendar <= point)
    if not keep.any():
        return None
    rows, columns = keep.any(axis=1), keep.any(axis=0)
    cut = np.where(keep, cumulative, np.nan)[rows][:, columns]
    return AsOf(steps, cut, np.where(keep, calendar, -1)[rows][:, columns], rows, columns)


@dataclass(frozen=True)
class Error:
    """AE02 for one method, origin and horizon."""

    method: str
    horizon_months: int
    origin: str
    estimate: float
    reference: float
    error: float  # (estimate - reference) / reference
    label: str  # ACTUAL or TODAY


@dataclass(frozen=True)
class Summary:
    method: str
    horizon_months: int
    origins: int
    bias: float
    mean_absolute_error: float
    root_mean_square_error: float


@dataclass(frozen=True)
class NotSummarised:
    method: str
    horizon_months: int
    reason: str


def ae02_errors(
    estimate: Sequence[float] | np.ndarray, reference: Sequence[float] | np.ndarray
) -> np.ndarray:
    """e = (U(c - h) - U_ref(c)) / U_ref(c); NaN where the reference is zero or missing."""
    estimate = np.asarray(estimate, dtype=float)
    reference = np.asarray(reference, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(np.isfinite(reference) & (reference != 0), estimate / reference - 1, np.nan)


def weighted_errors(
    errors: Sequence[float] | np.ndarray, reference: Sequence[float] | np.ndarray
) -> tuple[float, float, float]:
    """Bias, MAE and RMSE weighted by the reference, over the origins with an error (AE02;
    RMSE = sqrt(sum w e^2 / sum w), decision 0275)."""
    e = np.asarray(errors, dtype=float)
    w = np.asarray(reference, dtype=float)
    keep = np.isfinite(e) & np.isfinite(w)
    e, w = e[keep], w[keep]
    total = float(w.sum())
    return (
        float((w * e).sum()) / total,
        float((w * np.abs(e)).sum()) / total,
        math.sqrt(float((w * e**2).sum()) / total),
    )


@dataclass(frozen=True)
class RangeCalibration:
    method: str  # MT06 or MT11
    horizon_months: int
    origins: int  # origins with a range and a reference
    inside: int

    @property
    def share(self) -> float:
        return self.inside / self.origins if self.origins else float("nan")


@dataclass(frozen=True)
class ActualVersusExpected:
    """AE01 over a horizon for one origin: development seen against what c - h expected."""

    horizon_months: int
    origin: str
    actual: float
    expected: float

    @property
    def ratio(self) -> float:
        return self.actual / self.expected if self.expected else float("nan")


@dataclass(frozen=True)
class BackTest:
    origins: tuple[str, ...]
    reference: np.ndarray  # today's selected ultimate per origin
    mature: np.ndarray  # bool: the reference stands for the actual
    errors: tuple[Error, ...]
    summaries: tuple[Summary, ...]
    not_summarised: tuple[NotSummarised, ...]
    not_run: dict[tuple[str, int], str]  # (method, horizon): the method's reason
    ranges: tuple[RangeCalibration, ...]
    actual_versus_expected: tuple[ActualVersusExpected, ...]
    horizons_not_computed: dict[int, str]  # horizon: reason

    def run_off(self, method: str) -> dict[str, dict[int, float]]:
        """Ultimate of each origin across the past cut-offs (diagnostic)."""
        found: dict[str, dict[int, float]] = {}
        for e in self.errors:
            if e.method == method:
                found.setdefault(e.origin, {})[e.horizon_months] = e.estimate
        return found


def chain_ladder_runner(
    cumulative: np.ndarray, calendar: np.ndarray, rows: np.ndarray
) -> np.ndarray | Skipped:
    """MT02 with its defaults on the as-of triangle."""
    result = chain_ladder(cumulative, calendar=calendar)
    return result if isinstance(result, Skipped) else result.ultimate


def premium_runners(premium: Sequence[float] | np.ndarray) -> dict[str, Runner]:
    """MT03, MT04, MT05 and MT10 with their defaults: the Cape Cod ratio of the same as-of
    triangle is the data-derived prior of MT03 and MT05 (record 0011); `premium` is earned
    premium per origin of today's triangle."""
    premium = np.asarray(premium, dtype=float)

    def fitted(
        cumulative: np.ndarray, calendar: np.ndarray, rows: np.ndarray
    ) -> tuple[ChainLadder | Skipped, CapeCod | Skipped]:
        chain = chain_ladder(cumulative, calendar=calendar)
        if isinstance(chain, Skipped):
            return chain, chain
        return chain, cape_cod(chain, premium[rows])

    def prior(chain: ChainLadder, cc: CapeCod, rows: np.ndarray) -> BornhuetterFerguson | Skipped:
        return bornhuetter_ferguson(
            chain, premium[rows], cc.expected_loss_ratio, prior_source=DATA_DERIVED_PRIOR
        )

    def mt03(
        cumulative: np.ndarray, calendar: np.ndarray, rows: np.ndarray
    ) -> np.ndarray | Skipped:
        chain, cc = fitted(cumulative, calendar, rows)
        if isinstance(chain, Skipped):
            return chain
        if isinstance(cc, Skipped):
            return cc
        bf = prior(chain, cc, rows)
        return bf if isinstance(bf, Skipped) else bf.ultimate

    def mt04(
        cumulative: np.ndarray, calendar: np.ndarray, rows: np.ndarray
    ) -> np.ndarray | Skipped:
        _, cc = fitted(cumulative, calendar, rows)
        return cc if isinstance(cc, Skipped) else cc.ultimate

    def mt05(
        cumulative: np.ndarray, calendar: np.ndarray, rows: np.ndarray
    ) -> np.ndarray | Skipped:
        chain, cc = fitted(cumulative, calendar, rows)
        if isinstance(chain, Skipped):
            return chain
        if isinstance(cc, Skipped):
            return cc
        found = expected_loss_ratio(
            premium[rows], cc.expected_loss_ratio, chain.latest, source=DATA_DERIVED_PRIOR
        )
        return found if isinstance(found, Skipped) else found.ultimate

    def mt10(
        cumulative: np.ndarray, calendar: np.ndarray, rows: np.ndarray
    ) -> np.ndarray | Skipped:
        chain, cc = fitted(cumulative, calendar, rows)
        if isinstance(chain, Skipped):
            return chain
        bf = cc if isinstance(cc, Skipped) else prior(chain, cc, rows)
        found = select_ultimates(chain, bf)
        return found if isinstance(found, Skipped) else found.ultimate

    return {"MT03": mt03, "MT04": mt04, "MT05": mt05, "MT10": mt10}


def _expected_development(chain: ChainLadder, steps: int) -> np.ndarray:
    """U(c - h) (1 / CDF(a1) - 1 / CDF(a0)) per as-of origin (AE01 with the MT02 pattern)."""
    n_dev = len(chain.cdf)
    later = np.minimum(chain.latest_index + steps, n_dev - 1)
    reported_now = 1 / chain.cdf[later]
    # ages beyond the as-of triangle's last column have no factor: fully reported (tail 1)
    reported_now = np.where(
        chain.latest_index + steps > n_dev - 1, 1 / chain.tail_factor, reported_now
    )
    return chain.ultimate * (reported_now - 1 / chain.cdf_at_latest)


def back_test(
    cumulative: np.ndarray,
    calendar: np.ndarray,
    origins: Sequence[str],
    reference: Sequence[float] | np.ndarray,
    reported_share: Sequence[float] | np.ndarray,
    *,
    runners: Mapping[str, Runner] | None = None,
    horizons_months: Sequence[int] = HORIZONS_MONTHS,
    development_months: int = 12,
    mature_at: float = MATURE_AT,
    ranges: bool = True,
    bootstrap_rng: np.random.Generator | None = None,
    backtest_simulations: int = BACKTEST_SIMULATIONS,
    estimates: Mapping[tuple[str, int], np.ndarray | Skipped] | None = None,
) -> BackTest:
    """MT22 on one triangle (one group and measure). `reference` is today's selected ultimate
    and `reported_share` today's maturity (1 / CDF) per origin. `runners` re-run methods on the
    as-of triangles (default MT02 only); `estimates` gives ultimates already computed at past
    cut-offs, per (method, horizon) and aligned with today's origins (NaN where an origin had
    not started), for example from `modules.reserving.earlier_result`. With `bootstrap_rng`,
    MT11 is re-run with `backtest_simulations` samples for the range calibration."""
    cumulative = np.asarray(cumulative, dtype=float)
    reference = np.asarray(reference, dtype=float)
    mature = np.asarray(reported_share, dtype=float) >= mature_at
    runners = dict(runners) if runners is not None else {"MT02": chain_ladder_runner}
    labels = list(origins)
    found: dict[tuple[str, int], np.ndarray | Skipped] = dict(estimates or {})
    not_computed: dict[int, str] = {}
    calibrations: list[RangeCalibration] = []
    seen: list[ActualVersusExpected] = []
    latest = cumulative[np.arange(len(labels)), (~np.isnan(cumulative)).sum(axis=1) - 1]

    for h in horizons_months:
        if h <= 0 or h % development_months:
            not_computed[h] = (
                f"horizon {h} months is not a whole number of development periods of "
                f"{development_months} months"
            )
            continue
        cut = as_of(cumulative, calendar, h // development_months)
        if cut is None:
            not_computed[h] = f"nothing was known {h} months before the cut-off"
            continue
        rows = np.flatnonzero(cut.rows)
        for method, run in runners.items():
            result = run(cut.cumulative, cut.calendar, cut.rows)
            if isinstance(result, Skipped):
                found[(method, h)] = result
                continue
            aligned = np.full(len(labels), np.nan)
            aligned[rows] = result
            found[(method, h)] = aligned
        chain = chain_ladder(cut.cumulative, calendar=cut.calendar)
        if isinstance(chain, ChainLadder):
            expected = _expected_development(chain, h // development_months)
            for k, i in enumerate(rows):
                seen.append(
                    ActualVersusExpected(h, labels[i], float(latest[i] - chain.latest[k]),
                                         float(expected[k]))
                )  # fmt: skip
        if ranges:
            calibrations += _ranges(cut, rows, reference, h, bootstrap_rng, backtest_simulations)

    errors: list[Error] = []
    summaries: list[Summary] = []
    skipped: list[NotSummarised] = []
    not_run: dict[tuple[str, int], str] = {}
    for (method, h), result in found.items():
        if isinstance(result, Skipped):
            not_run[(method, h)] = result.reason
            continue
        e = ae02_errors(result, reference)
        for i in np.flatnonzero(np.isfinite(e)):
            errors.append(
                Error(method, h, labels[i], float(result[i]), float(reference[i]), float(e[i]),
                      ACTUAL if mature[i] else TODAY)
            )  # fmt: skip
        count = int(np.isfinite(e).sum())
        if count < MIN_ORIGINS:
            skipped.append(
                NotSummarised(method, h, f"only {count} origins with a reference (fewer than "
                              f"{MIN_ORIGINS})")
            )  # fmt: skip
            continue
        summaries.append(Summary(method, h, count, *weighted_errors(e, reference)))
    return BackTest(
        origins=tuple(labels),
        reference=reference,
        mature=mature,
        errors=tuple(errors),
        summaries=tuple(summaries),
        not_summarised=tuple(skipped),
        not_run=not_run,
        ranges=tuple(calibrations),
        actual_versus_expected=tuple(seen),
        horizons_not_computed=not_computed,
    )


def _ranges(
    cut: AsOf,
    rows: np.ndarray,
    reference: np.ndarray,
    horizon: int,
    rng: np.random.Generator | None,
    simulations: int,
) -> list[RangeCalibration]:
    """Share of origins whose reference reserve lies inside the past 5 to 95 per cent range."""
    low, high = RANGE
    found: list[RangeCalibration] = []
    latest = cut.cumulative[np.arange(len(rows)), (~np.isnan(cut.cumulative)).sum(axis=1) - 1]
    target = reference[rows] - latest
    fit = mack(cut.cumulative, calendar=cut.calendar)
    if isinstance(fit, Mack):
        per_origin, _ = fit.ranges(percentiles=(low, high))
        inside = [
            r.percentiles[low] <= t <= r.percentiles[high]
            for r, t in zip(per_origin, target, strict=True)
            if r is not None and np.isfinite(t)
        ]
        found.append(RangeCalibration("MT06", horizon, len(inside), int(sum(inside))))
    if rng is not None:
        boot = odp_bootstrap(cut.cumulative, rng, n_simulations=simulations)
        if isinstance(boot, OdpBootstrap):
            inside = []
            for k, t in enumerate(target):
                draws = boot.reserves[:, k]
                if np.isfinite(t) and boot.chain.reserve[k] != 0:
                    inside.append(np.quantile(draws, low) <= t <= np.quantile(draws, high))
            found.append(RangeCalibration("MT11", horizon, len(inside), int(sum(inside))))
    return found
