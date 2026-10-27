"""Frequency–severity projection (MT16): ultimate as ultimate claim count times severity.

Non-nil reported counts are developed with the chain ladder (MT02); severity is the
chain-ladder ultimate of the severity measure over the ultimate count, trended log-linearly
across the mature origins and projected for every origin (the projection replaces the observed
severity of mature origins too, decision 0618). Maturity comes from the chain ladder of the
severity measure. Catastrophe claims are projected apart at their chain-ladder ultimate.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from actuarycanary.methods.chain_ladder import ChainLadder, Skipped, chain_ladder
from actuarycanary.methods.diagnostics import WARNING, Diagnostic

MATURITY_FOR_TREND = 0.9
MIN_TREND_ORIGINS = 3
NO_EXPOSURE = "no earned exposure (policies not loaded): frequency is not shown"


@dataclass(frozen=True)
class Trend:
    """ln y = intercept + slope t by ordinary least squares; slope 0 when held constant."""

    intercept: float
    slope: float
    origins: tuple[int, ...]  # indices the trend rests on

    @property
    def rate(self) -> float:
        """Growth per unit of t (per year for annual origins)."""
        return float(np.expm1(self.slope))

    def at(self, t: np.ndarray) -> np.ndarray:
        return np.exp(self.intercept + self.slope * np.asarray(t, dtype=float))


@dataclass(frozen=True)
class FrequencySeverity:
    count_chain: ChainLadder
    measure_chain: ChainLadder
    ultimate_counts: np.ndarray  # N(i)
    reported_share: np.ndarray  # p(i) of the severity measure
    severity: np.ndarray  # U(i) / N(i) for every origin, observed
    mature: np.ndarray  # bool: p(i) at least maturity_for_trend
    severity_trend: Trend
    projected_severity: np.ndarray
    catastrophe_ultimate: np.ndarray  # zero without catastrophe claims
    exposure: np.ndarray | None
    frequency: np.ndarray | None  # N(i) / E(i)
    frequency_trend: Trend | None
    origin_time: np.ndarray
    value_basis: str
    diagnostics: tuple[Diagnostic, ...]

    @property
    def ultimate(self) -> np.ndarray:
        return self.ultimate_counts * self.projected_severity + self.catastrophe_ultimate

    @property
    def latest(self) -> np.ndarray:
        return self.measure_chain.latest

    @property
    def chain_ladder_ultimate(self) -> np.ndarray:
        """The severity measure's chain-ladder ultimate (diagnostic, without catastrophes)."""
        return self.measure_chain.ultimate


def _log_trend(t: np.ndarray, y: np.ndarray, rows: np.ndarray) -> Trend:
    slope, intercept = np.polyfit(t[rows], np.log(y[rows]), 1)
    return Trend(float(intercept), float(slope), tuple(int(i) for i in rows))


def frequency_severity(
    counts: np.ndarray,
    measure: np.ndarray,
    *,
    exposure: Sequence[float] | np.ndarray | None = None,
    origin_time: Sequence[float] | np.ndarray | None = None,
    catastrophes: np.ndarray | None = None,
    maturity_for_trend: float = MATURITY_FOR_TREND,
    min_trend_origins: int = MIN_TREND_ORIGINS,
    value_basis: str = "NOMINAL",
    calendar: np.ndarray | None = None,
    min_origins: int = 3,
    origins: Sequence[str] | None = None,
) -> FrequencySeverity | Skipped:
    """MT16 on a cumulative non-nil count triangle and the cumulative triangle of the severity
    measure, both without catastrophe claims; `catastrophes` is the cumulative triangle of the
    catastrophe claims of the same measure. `origin_time` t(i) defaults to 0, 1, ..."""
    count_chain = chain_ladder(counts, min_origins=min_origins, calendar=calendar)
    if isinstance(count_chain, Skipped):
        return Skipped("MT16", f"count chain ladder: {count_chain.reason}")
    measure_chain = chain_ladder(measure, min_origins=min_origins, calendar=calendar)
    if isinstance(measure_chain, Skipped):
        return Skipped("MT16", measure_chain.reason)
    n_origins = len(count_chain.latest)
    labels = list(origins) if origins is not None else [str(i) for i in range(n_origins)]
    t = (
        np.arange(n_origins, dtype=float)
        if origin_time is None
        else np.asarray(origin_time, dtype=float)
    )
    diagnostics: list[Diagnostic] = []

    n_ult = count_chain.ultimate
    p = 1 / measure_chain.cdf_at_latest
    with np.errstate(divide="ignore", invalid="ignore"):
        severity = np.where(n_ult > 0, measure_chain.ultimate / n_ult, np.nan)
    usable = np.isfinite(severity) & (severity > 0)
    mature = (p >= maturity_for_trend) & usable
    rows = np.flatnonzero(mature)
    if len(rows) == 0:
        return Skipped("MT16", f"no origin with a reported share of at least {maturity_for_trend}")
    if len(rows) < min_trend_origins:
        mean = float(severity[rows].mean())
        trend = Trend(float(np.log(mean)), 0.0, tuple(int(i) for i in rows))
        diagnostics.append(
            Diagnostic(
                "MT16",
                "SEVERITY_HELD_CONSTANT",
                WARNING,
                f"only {len(rows)} mature origin{'s' if len(rows) != 1 else ''} (fewer than "
                f"{min_trend_origins}): severity is held constant at their mean {mean:,.2f}",
                value=float(len(rows)),
            )
        )
    else:
        trend = _log_trend(t, severity, rows)

    cat = np.zeros(n_origins)
    if catastrophes is not None:
        cat_chain = chain_ladder(catastrophes, min_origins=1, calendar=calendar)
        cat = (
            np.nan_to_num(cat_chain.ultimate)
            if isinstance(cat_chain, ChainLadder)
            else np.nan_to_num(np.nanmax(catastrophes, axis=1))
        )

    frequency = frequency_trend = exposure_array = None
    if exposure is None:
        diagnostics.append(Diagnostic("MT16", "NO_EXPOSURE", WARNING, NO_EXPOSURE))
    else:
        exposure_array = np.asarray(exposure, dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            frequency = np.where(exposure_array > 0, n_ult / exposure_array, np.nan)
        positive = np.flatnonzero(np.isfinite(frequency) & (frequency > 0))
        if len(positive) >= 2:
            frequency_trend = _log_trend(t, frequency, positive)
        for i in np.flatnonzero(~(exposure_array > 0)):
            diagnostics.append(
                Diagnostic(
                    "MT16",
                    "NO_EXPOSURE",
                    WARNING,
                    f"origin {labels[i]} has no positive earned exposure: no frequency",
                    labels[i],
                )
            )

    return FrequencySeverity(
        count_chain=count_chain,
        measure_chain=measure_chain,
        ultimate_counts=n_ult,
        reported_share=p,
        severity=severity,
        mature=mature,
        severity_trend=trend,
        projected_severity=trend.at(t),
        catastrophe_ultimate=cat,
        exposure=exposure_array,
        frequency=frequency,
        frequency_trend=frequency_trend,
        origin_time=t,
        value_basis=value_basis,
        diagnostics=tuple(diagnostics),
    )
