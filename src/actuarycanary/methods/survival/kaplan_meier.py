"""Kaplan-Meier product-limit estimate with Greenwood variance and log-log intervals (MT19).

At the distinct event times t(m) with d(m) events among n(m) at risk, S(t) is the product of
(1 - d/n) and the Greenwood sum of d / (n (n - d)) gives the variance S(t)^2 times the sum. The
interval is S^exp(+-z sigma / |ln S|) with sigma the square root of the Greenwood sum, the plus
sign giving the lower limit. A percentile of the time to event is the first time the curve is at
or below one minus the percentile; its interval is the set of times at which the interval of the
curve contains that level (Brookmeyer and Crowley).

The log-rank test compares the curves of several groups; its sign tells which group has the
higher hazard.
"""

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats

CONFIDENCE = 0.95
LEVEL_TOLERANCE = 1e-12  # a curve at 0.5 within rounding counts as having reached 0.5


@dataclass(frozen=True)
class KaplanMeier:
    """The curve at its distinct event times."""

    time: np.ndarray
    at_risk: np.ndarray
    events: np.ndarray
    censored: np.ndarray  # observations censored after this event time and before the next one
    survival: np.ndarray
    greenwood_sum: np.ndarray  # sum of d / (n (n - d)) up to the time; inf where n = d
    standard_error: np.ndarray  # S sqrt(greenwood sum); NaN where it is not defined
    lower: np.ndarray
    upper: np.ndarray
    confidence: float
    n: int
    n_events: int

    @property
    def share_censored(self) -> float:
        return 1.0 - self.n_events / self.n if self.n else math.nan


def kaplan_meier(
    time: np.ndarray, event: np.ndarray, confidence: float = CONFIDENCE
) -> KaplanMeier:
    """Product-limit estimate of `time` with `event` True where the event was seen and False
    where the observation is censored. An observation censored at an event time stays in the
    risk set of that time (it is observed up to and including it)."""
    t = np.asarray(time, dtype=np.float64)
    e = np.asarray(event, dtype=bool)
    if t.shape != e.shape or t.ndim != 1:
        raise ValueError("time and event must be one-dimensional and of equal length")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must lie between 0 and 1")
    n = len(t)
    event_times, events = np.unique(t[e], return_counts=True)
    at_risk = n - np.searchsorted(np.sort(t), event_times, side="left")
    with np.errstate(divide="ignore", invalid="ignore"):
        steps = 1.0 - events / at_risk
        survival = np.cumprod(steps)
        greenwood = np.cumsum(events / (at_risk * (at_risk - events).astype(np.float64)))
        sigma = np.sqrt(greenwood)
        standard_error = survival * sigma
        z = float(stats.norm.ppf(0.5 + confidence / 2.0))
        theta = z * sigma / np.abs(np.log(survival))
        lower = survival ** np.exp(theta)
        upper = survival ** np.exp(-theta)
    undefined = ~np.isfinite(greenwood) | (survival <= 0.0)
    standard_error[undefined] = math.nan
    lower[undefined] = math.nan
    upper[undefined] = math.nan
    after = np.searchsorted(event_times, t[~e], side="right")  # event times at or before it
    censored = np.bincount(after, minlength=len(event_times) + 1)[1:]
    return KaplanMeier(
        event_times, at_risk, events, censored.astype(np.int64), survival, greenwood,
        standard_error, lower, upper, confidence, n, int(e.sum()),
    )  # fmt: skip


def survival_at(curve: KaplanMeier, t: float) -> float:
    """S(t), 1 before the first event."""
    index = int(np.searchsorted(curve.time, t, side="right")) - 1
    return 1.0 if index < 0 else float(curve.survival[index])


def percentile_time(curve: KaplanMeier, p: float) -> tuple[float, float, float]:
    """(time, lower, upper) of the p-th percentile of the time to event: the first time with
    S <= 1 - p, and the first times at which the lower and the upper limit of the curve reach
    1 - p (the lower limit of the curve gets there first, so it gives the lower limit of the
    time). NaN where the curve (or its limit) never gets there: beyond the observed range."""
    level = 1.0 - p + LEVEL_TOLERANCE

    def first(values: np.ndarray) -> float:
        with np.errstate(invalid="ignore"):
            hit = np.flatnonzero(values <= level)
        return float(curve.time[hit[0]]) if hit.size else math.nan

    return first(curve.survival), first(curve.lower), first(curve.upper)


@dataclass(frozen=True)
class LogRank:
    groups: tuple[str, ...]
    observed: np.ndarray
    expected: np.ndarray
    statistic: float
    df: int
    p_value: float


def log_rank(time: np.ndarray, event: np.ndarray, group: np.ndarray) -> LogRank:
    """The log-rank test of equal hazards in the groups of `group`. Observed minus expected
    events above zero means a group's hazard is higher than the pooled one."""
    t = np.asarray(time, dtype=np.float64)
    e = np.asarray(event, dtype=bool)
    labels, index = np.unique(np.asarray(group).astype(str), return_inverse=True)
    k = len(labels)
    times = np.unique(t[e])
    observed = np.array([float(np.sum(e & (index == g))) for g in range(k)])
    variance = np.zeros((k, k))
    # risk sets by group at each event time: counts of the sorted times from it on
    at_risk = np.zeros((len(times), k))
    died = np.zeros((len(times), k))
    for g in range(k):
        tg = t[index == g]
        eg = t[(index == g) & e]
        at_risk[:, g] = len(tg) - np.searchsorted(np.sort(tg), times, side="left")
        died[:, g] = np.searchsorted(np.sort(eg), times, side="right") - np.searchsorted(
            np.sort(eg), times, side="left"
        )
    n = at_risk.sum(axis=1)
    d = died.sum(axis=1)
    share = at_risk / n[:, None]
    expected = (d[:, None] * share).sum(axis=0)
    # covariance of the observed counts at each time: d (n - d) / (n - 1) * (diag(p) - p p')
    for m in range(len(times)):
        if n[m] <= 1:
            continue
        scale = d[m] * (n[m] - d[m]) / (n[m] - 1.0)
        p = share[m]
        variance += scale * (np.diag(p) - np.outer(p, p))
    if k < 2:
        return LogRank(tuple(labels), observed, expected, 0.0, 0, math.nan)
    difference = (observed - expected)[: k - 1]
    reduced = variance[: k - 1, : k - 1]
    try:
        statistic = float(difference @ np.linalg.solve(reduced, difference))
    except np.linalg.LinAlgError:
        statistic = math.nan
    df = k - 1
    p_value = float(stats.chi2.sf(statistic, df)) if math.isfinite(statistic) else math.nan
    return LogRank(tuple(labels), observed, expected, statistic, df, p_value)
